"""Single deployment-wide worker with PostgreSQL lease and resumable queue.

Only short commits hold repository locks. Research I/O can be cancelled by a
separate API process. Expired lease recovery resumes persisted model messages;
SMTP uses stable message IDs but does not promise exactly-once remote delivery.
"""
from __future__ import annotations
import asyncio
import copy
import json
import os
import signal
import sys
import uuid
from datetime import datetime, timezone, timedelta
from . import pharma_scope_app as api
from .repository import PersistentStateStore, restore_state, state_payload
from .notifications import SMTPAdapter

_STOP=asyncio.Event()
_OWNER=f'{os.getpid()}:{uuid.uuid4()}'


def refresh():
    if api.state_store:
        payload=api.state_store.load()
        if payload: restore_state(api.state,payload)


def save(): api.checkpoint()


class WorkerInterrupted(RuntimeError):
    """Stop this iteration without starting another external operation."""


class WorkerLeaseLost(WorkerInterrupted):
    pass


def ensure_active():
    if _STOP.is_set():
        raise WorkerInterrupted('Worker is stopping')
    if api.state_store and not api.state_store.claim_worker(_OWNER):
        raise WorkerLeaseLost('Worker lease lost')


async def supervise(task, run_id=None):
    async def cancel(interrupted):
        if interrupted and run_id and not task.done():
            api.state.runs[run_id]['interrupted'] = True
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    try:
        ensure_active()
        while not task.done():
            await asyncio.wait({task}, timeout=1)
            if task.done():
                break
            ensure_active()
            if run_id and api.state_store:
                observer = PersistentStateStore(api.state_store.url)
                try:
                    current = observer.load() or {}
                    if current.get('runs', {}).get(run_id, {}).get('status') == 'cancelled':
                        await cancel(False)
                finally:
                    observer.engine.dispose()
        return await task
    except WorkerInterrupted:
        await cancel(True)
        raise
    except asyncio.CancelledError:
        # A heartbeat may cancel the outer iteration. Always join the child so
        # it cannot keep writing checkpoints after the worker slot is released.
        interrupted = bool(asyncio.current_task().cancelling())
        await cancel(interrupted)
        if interrupted:
            raise


def schedule_due():
    for sub in list(api.state.subscriptions.values()):
        ensure_active()
        if not sub.get('enabled'):
            continue
        try:
            scheduled = sub['next_run_at']
            if api.parse_time(scheduled) > datetime.now(timezone.utc):
                continue
            # Validate first; an invalid schedule cannot enqueue a broken job.
            next_run = api.schedule_occurrences(sub)[0]['utc']
            key = str(uuid.uuid5(uuid.NAMESPACE_URL, sub['id'] + scheduled))
            api.state.occurrences.setdefault(key, {
                'id': key, 'workspace_id': sub['workspace_id'],
                'subscription_id': sub['id'], 'scheduled_at': scheduled,
                'created_at': api.now(), 'state': 'queued', 'run_id': None,
            })
            sub['next_run_at'] = next_run
        except Exception:
            # Do not retry a malformed schedule on every poll or stop unrelated
            # subscriptions. The owner can fix and explicitly re-enable it.
            sub.update(enabled=False, next_run_at=None,
                       last_outcome='schedule_failed', last_error_code='INVALID_SCHEDULE')


def latest_identity(workspace_id, user_id):
    if api.state_store:
        observer = PersistentStateStore(api.state_store.url)
        try:
            latest = observer.load() or {}
        finally:
            observer.engine.dispose()
        user = latest.get('users', {}).get(user_id)
        member = latest.get('memberships', {}).get(workspace_id + '|' + user_id)
    else:
        user = api.state.users.get(user_id)
        member = api.membership(workspace_id, user or {'id': ''})
    if not user or not user.get('is_active', True) or not member or not member.get('enabled', True):
        return None, None
    return user, member


def fail_occurrence(occurrence, live_sub, code):
    occurrence.update(state='failed', error_code=code)
    if live_sub is not None:
        live_sub['last_outcome'] = 'failed'
        live_sub['last_error_code'] = code


async def process_occurrence(occurrence, live_sub):
    if live_sub is None:
        fail_occurrence(occurrence, live_sub, 'SUBSCRIPTION_MISSING')
        return
    sub = occurrence.get('frozen_subscription') or live_sub
    if occurrence['state'] in ('queued', 'syncing'):
        if not live_sub.get('enabled', True):
            fail_occurrence(occurrence, live_sub, 'SUBSCRIPTION_DISABLED')
            return
        # Source/model I/O may span a permission change in another API process.
        # Use current authorization while keeping the original frozen scope.
        owner, member = latest_identity(sub['workspace_id'], sub['owner_id'])
        if not member or member.get('role') not in ('analyst', 'reviewer', 'admin'):
            fail_occurrence(occurrence, live_sub, 'OWNER_PERMISSION_REVOKED')
            return
    if occurrence['state'] == 'queued':
        job_id = str(uuid.uuid5(uuid.NAMESPACE_URL, occurrence['id'] + ':sync'))
        api.state.jobs.setdefault(job_id, {
            'id': job_id, 'workspace_id': sub['workspace_id'], 'kind': 'ingest', 'state': 'queued',
            'created_at': api.now(), 'payload': {'drug_ids': sub['drug_ids'],
                'sources': sub['source_allowlist'], 'mode': 'refresh_linked'},
            'progress': {'processed': 0, 'total': None}, 'attempt': 0,
        })
        occurrence.update(state='syncing', job_id=job_id, frozen_subscription=copy.deepcopy(sub))
    if occurrence['state'] == 'syncing':
        job = api.state.jobs.get(occurrence['job_id'], {})
        if job.get('state') not in ('completed', 'partial', 'failed'):
            return
        if job['state'] == 'failed':
            fail_occurrence(occurrence, live_sub, job.get('error_code') or 'SOURCE_SYNC_FAILED')
            occurrence['coverage'] = job.get('coverage')
            live_sub['last_outcome'] = 'source_failed'
            return
        linked = {x['record_id'] for x in api.state.links.values()
                  if x.get('workspace_id') == sub['workspace_id']
                  and x.get('drug_id') in sub['drug_ids'] and x.get('status') == 'approved'}
        cursor = sub.get('last_delivered_at') or '0000'
        changed = any(o.get('workspace_id') == sub['workspace_id']
                      and o.get('record_id') in linked and (o.get('fetched_at') or '') > cursor
                      and o.get('outcome') in ('baseline', 'changed')
                      for o in api.state.observations.values())
        if not changed:
            outcome = 'no_change' if job['state'] == 'completed' else 'source_partial'
            occurrence.update(state=outcome, coverage=job.get('coverage'))
            live_sub['last_outcome'] = outcome
            return
        ctx = {'user': owner, 'membership': member, 'workspace_id': sub['workspace_id']}
        stamp = datetime.now(timezone.utc)
        start = sub.get('last_delivered_at') or (stamp - timedelta(days=7)).isoformat()
        payload = {'question': f'为订阅{sub["name"]}整理来源变化、证据和资料缺口。',
                   'drug_ids': sub['drug_ids'], 'source_allowlist': sub['source_allowlist'],
                   'time_range': {'start': start, 'end_exclusive': stamp.isoformat(),
                                  'timezone': sub['schedule']['timezone']}}
        result = await api.run_create(sub['workspace_id'], api._request_with_json(payload),
                                      ctx, 'occurrence:' + occurrence['id'])
        body = json.loads(result.body) if hasattr(result, 'body') else result
        occurrence.update(state='researching', run_id=body['id'])
    if occurrence['state'] == 'researching':
        run = api.state.runs.get(occurrence['run_id'], {})
        if run.get('status') == 'completed':
            occurrence['state'] = 'awaiting_review'
            live_sub['last_outcome'] = 'awaiting_review'
        elif run.get('status') in ('failed', 'cancelled'):
            occurrence.update(state=run['status'], error_code=run.get('error_code'))
            live_sub['last_outcome'] = run['status']


async def process_occurrences():
    for occurrence in list(api.state.occurrences.values()):
        ensure_active()
        if occurrence.get('state') not in ('queued', 'syncing', 'researching'):
            continue
        live_sub = api.state.subscriptions.get(occurrence.get('subscription_id'))
        try:
            await process_occurrence(occurrence, live_sub)
        except WorkerInterrupted:
            raise
        except Exception as exc:
            # Data/permission failures are terminal for this occurrence only.
            # Infrastructure failures must retain the queue for recovery.
            from sqlalchemy.exc import SQLAlchemyError
            from .repository import RepositoryUnavailable, RepositoryConflict
            if isinstance(exc, (SQLAlchemyError, RepositoryUnavailable, RepositoryConflict)):
                raise
            detail = getattr(exc, 'detail', None)
            code = detail.get('code', 'OCCURRENCE_PROCESSING_FAILED') if isinstance(detail, dict) else 'OCCURRENCE_PROCESSING_FAILED'
            fail_occurrence(occurrence, live_sub, code)


async def deliver_pending():
    smtp = SMTPAdapter()
    for delivery in list(api.state.deliveries.values()):
        ensure_active()
        if delivery.get('channel') != 'email' or delivery.get('state') != 'queued':
            continue
        user, member = latest_identity(delivery['workspace_id'], delivery['recipient_user_id'])
        if user is None or member is None:
            delivery.update(state='failed', error_code='RECIPIENT_DISABLED')
            save()
            continue
        delivery.update(state='sending', attempt=delivery.get('attempt', 0) + 1)
        save()
        result = await supervise(asyncio.create_task(smtp.send(
            recipient=user['email'], subject=delivery.get('subject', 'PharmaScope'),
            body='A reviewed report is available in your PharmaScope inbox.',
            idempotency_key=delivery['id'])))
        delivery.update(state=result.state, error_code=result.error_code, message_id=result.message_id,
                        attempts=result.attempts, delivered_at=api.now() if result.state == 'sent' else None)
        save()


async def _run_once():
    ensure_active()
    refresh()
    schedule_due()
    # SMTP interrupted during send has uncertain outcome; do not silently retry.
    for delivery in api.state.deliveries.values():
        if delivery.get('state')=='sending': delivery.update(state='failed',error_code='SMTP_OUTCOME_UNKNOWN')
    await process_occurrences()
    save()
    processed=0
    for job_id,job in list(api.state.jobs.items()):
        ensure_active()
        if job.get('kind')=='ingest' and job.get('state') in ('queued','running'):
            if os.getenv('PHARMA_RUNTIME_MODE','live') in ('replay','demo'):
                job.update(state='completed',coverage=[{'source':s,'state':'complete','mode':'replay'} for s in job['payload']['sources']])
            else:
                await supervise(asyncio.create_task(api._execute_source_sync(job_id,job.get('payload',{}))))
            save();processed+=1
    ensure_active()
    await process_occurrences();save()
    for run_id,run in list(api.state.runs.items()):
        ensure_active()
        if run.get('status') in ('queued','running') and run.get('runtime_mode')=='live':
            if run['status']=='running': api.emit(run_id,'run.resumed',{'checkpoint':bool(run.get('checkpoint'))})
            await supervise(asyncio.create_task(api._execute_live_run(run_id,run['frozen_request'])),run_id)
            processed+=1
    ensure_active()
    await process_occurrences();save()
    ensure_active()
    await deliver_pending()
    if api.state_store: api.state_store.claim_worker(_OWNER)
    return processed


async def run_once():
    if api.state_store is None: return await _run_once()
    with api.state_store.worker_slot() as acquired:
        if not acquired or not api.state_store.claim_worker(_OWNER): return 0
        current=asyncio.current_task()
        async def heartbeat():
            while True:
                await asyncio.sleep(5)
                try: owned=api.state_store.claim_worker(_OWNER)
                except Exception: owned=False
                if not owned:
                    current.cancel()
                    return
        heartbeat_task=asyncio.create_task(heartbeat())
        try: return await _run_once()
        finally:
            heartbeat_task.cancel()
            try: await heartbeat_task
            except asyncio.CancelledError: pass


async def main():
    if api.state_store is None: raise SystemExit('Worker requires PHARMA_DATABASE_URL and migrated database')
    loop=asyncio.get_running_loop()
    for sig in (signal.SIGTERM,signal.SIGINT): loop.add_signal_handler(sig,_STOP.set)
    while not _STOP.is_set():
        try: await run_once()
        except WorkerInterrupted:
            if not _STOP.is_set(): print('worker_lease_lost', file=sys.stderr, flush=True)
        except Exception as exc:
            # Exception type only: driver/model errors can contain credentials.
            print('worker_iteration_failed:'+type(exc).__name__,file=sys.stderr,flush=True)
        try: await asyncio.wait_for(_STOP.wait(),timeout=float(os.getenv('PHARMA_WORKER_POLL_SECONDS','2')))
        except asyncio.TimeoutError: pass

if __name__=='__main__':
    if '--healthcheck' in sys.argv:
        try: healthy=api.state_store is not None and api.state_store.healthy_worker()
        except Exception: healthy=False
        raise SystemExit(0 if healthy else 1)
    asyncio.run(main())
