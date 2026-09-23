"""Queue isolation, current authorization and worker interruption regressions."""
import asyncio
import copy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from backend import pharma_scope_app as api
from backend import worker
from backend.notifications import DeliveryResult
from backend.repository import PersistentStateStore, state_payload


@pytest.fixture
def state(monkeypatch):
    monkeypatch.setenv('PHARMA_RUNTIME_MODE', 'replay')
    state = api.DomainState()
    state.subscriptions = {}
    state.occurrences = {}
    state.jobs = {}
    state.deliveries = {}
    monkeypatch.setattr(api, 'state', state)
    monkeypatch.setattr(api, 'state_store', None)
    monkeypatch.setattr(worker, '_STOP', asyncio.Event())
    return state


def subscription(state, *, owner=None):
    sid = api.uid()
    sub = {'id': sid, 'workspace_id': api.DEFAULT_WORKSPACE,
           'owner_id': owner or api.DEFAULT_USER, 'name': 'Recovery regression',
           'drug_ids': [next(iter(state.drugs))], 'source_allowlist': ['ctgov'],
           'enabled': True, 'next_run_at': '2000-01-01T00:00:00Z',
           'schedule': {'frequency': 'daily', 'timezone': 'UTC', 'local_time': '09:00'}}
    state.subscriptions[sid] = sub
    return sub


def occurrence(state, sub, status='syncing'):
    oid, job_id = api.uid(), api.uid()
    result = {'id': oid, 'workspace_id': sub['workspace_id'], 'subscription_id': sub['id'],
              'state': status, 'job_id': job_id, 'frozen_subscription': copy.deepcopy(sub)}
    state.occurrences[oid] = result
    state.jobs[job_id] = {'id': job_id, 'workspace_id': sub['workspace_id'],
                          'kind': 'ingest', 'state': 'completed', 'coverage': []}
    record = next(iter(state.records))
    state.links[api.uid()] = {'workspace_id': sub['workspace_id'], 'record_id': record,
                              'drug_id': sub['drug_ids'][0], 'status': 'approved'}
    observation = api.uid()
    state.observations[observation] = {'id': observation, 'workspace_id': sub['workspace_id'],
                                      'record_id': record, 'fetched_at': '2026-01-01T00:00:00Z',
                                      'outcome': 'changed'}
    return result


def test_invalid_schedule_disables_only_its_subscription(state):
    invalid = subscription(state)
    invalid['schedule']['timezone'] = 'Not/AZone'
    missing_time = subscription(state)
    missing_time['next_run_at'] = None
    valid = subscription(state)
    worker.schedule_due()
    assert invalid['last_error_code'] == 'INVALID_SCHEDULE' and not invalid['enabled']
    assert missing_time['last_error_code'] == 'INVALID_SCHEDULE'
    assert {item['subscription_id'] for item in state.occurrences.values()} == {valid['id']}
    count = len(state.occurrences)
    worker.schedule_due()
    assert len(state.occurrences) == count


@pytest.mark.asyncio
async def test_owner_revoked_after_sync_does_not_poison_other_occurrences(state, monkeypatch):
    bad = occurrence(state, subscription(state))
    reviewer = next(user['id'] for user in state.users.values() if user['email'].startswith('reviewer@'))
    good = occurrence(state, subscription(state, owner=reviewer))
    state.memberships[(api.DEFAULT_WORKSPACE, api.DEFAULT_USER)]['enabled'] = False
    calls = []
    async def create(ws, request, ctx, key):
        calls.append(ctx['user']['id'])
        return {'id': api.uid()}
    monkeypatch.setattr(api, 'run_create', create)
    await worker.process_occurrences()
    assert bad['state'] == 'failed' and bad['error_code'] == 'OWNER_PERMISSION_REVOKED'
    assert good['state'] == 'researching' and calls == [reviewer]


@pytest.mark.asyncio
async def test_one_invalid_occurrence_does_not_block_other_work(state, monkeypatch):
    bad_sub, good_sub = subscription(state), subscription(state)
    bad, good = occurrence(state, bad_sub), occurrence(state, good_sub)
    calls = []
    async def create(ws, request, ctx, key):
        calls.append(key)
        if key == 'occurrence:' + bad['id']:
            raise HTTPException(422, detail={'code': 'INVALID_SCOPE'})
        return {'id': api.uid()}
    monkeypatch.setattr(api, 'run_create', create)
    await worker.process_occurrences()
    assert bad['state'] == 'failed' and bad['error_code'] == 'INVALID_SCOPE'
    assert good['state'] == 'researching' and len(calls) == 2
    assert bad_sub['last_outcome'] == 'failed'
    # Terminal poison items cannot execute again on the next poll.
    await worker.process_occurrences()
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_sync_uses_frozen_scope_after_subscription_edit(state, monkeypatch):
    sub = subscription(state)
    item = occurrence(state, sub, status='queued')
    item.pop('frozen_subscription')
    item.pop('job_id')
    await worker.process_occurrences()
    assert item['state'] == 'syncing'
    frozen = copy.deepcopy(item['frozen_subscription'])
    sub['source_allowlist'].append('pubmed')
    sub['schedule']['timezone'] = 'Edited/Invalid'
    assert item['frozen_subscription'] == frozen
    state.jobs[item['job_id']]['state'] = 'completed'
    captured = []
    async def create(ws, request, ctx, key):
        captured.append(await request.json())
        return {'id': api.uid()}
    monkeypatch.setattr(api, 'run_create', create)
    await worker.process_occurrences()
    assert item['state'] == 'researching'
    assert captured[0]['source_allowlist'] == ['ctgov']
    assert captured[0]['time_range']['timezone'] == 'UTC'


@pytest.mark.asyncio
async def test_permission_is_read_from_repository_not_worker_cache(state, monkeypatch, tmp_path):
    store = PersistentStateStore(f'sqlite:///{tmp_path}/permission.db')
    store.save(state_payload(state))
    monkeypatch.setattr(api, 'state_store', store)
    item = occurrence(state, subscription(state))
    other = PersistentStateStore(store.url)
    current = other.load()
    current['memberships'][api.DEFAULT_WORKSPACE + '|' + api.DEFAULT_USER]['role'] = 'reader'
    other.save(current)
    assert state.memberships[(api.DEFAULT_WORKSPACE, api.DEFAULT_USER)]['role'] == 'analyst'
    await worker.process_occurrences()
    assert item['error_code'] == 'OWNER_PERMISSION_REVOKED'
    other.engine.dispose()
    store.engine.dispose()


@pytest.mark.asyncio
async def test_database_outage_retains_occurrence_for_recovery(state, monkeypatch):
    item = occurrence(state, subscription(state))
    def unavailable(*args):
        raise SQLAlchemyError('database unavailable')
    monkeypatch.setattr(worker, 'latest_identity', unavailable)
    with pytest.raises(SQLAlchemyError):
        await worker.process_occurrences()
    assert item['state'] == 'syncing' and 'error_code' not in item


@pytest.mark.asyncio
async def test_lease_loss_cancels_child_and_stops_iteration(state, monkeypatch):
    run_id = next(iter(state.runs))
    began, stopped = asyncio.Event(), asyncio.Event()
    calls = 0
    def claim(owner):
        nonlocal calls
        calls += 1
        return calls == 1
    monkeypatch.setattr(api, 'state_store', SimpleNamespace(claim_worker=claim))
    async def child():
        began.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
    task = asyncio.create_task(child())
    with pytest.raises(worker.WorkerLeaseLost):
        await worker.supervise(task, run_id)
    assert began.is_set() and stopped.is_set() and task.done()
    assert state.runs[run_id]['interrupted']


@pytest.mark.asyncio
async def test_parent_cancellation_joins_research_before_releasing_slot(state):
    run_id = next(iter(state.runs))
    began, stopped = asyncio.Event(), asyncio.Event()
    async def child():
        began.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
    task = asyncio.create_task(child())
    supervisor = asyncio.create_task(worker.supervise(task, run_id))
    await began.wait()
    supervisor.cancel()
    with pytest.raises(asyncio.CancelledError):
        await supervisor
    assert stopped.is_set() and task.done()
    assert state.runs[run_id]['interrupted']


@pytest.mark.asyncio
async def test_shutdown_after_smtp_never_sends_next_delivery(state, monkeypatch):
    recipient = api.DEFAULT_USER
    for identifier in ('first', 'second'):
        state.deliveries[identifier] = {'id': identifier, 'workspace_id': api.DEFAULT_WORKSPACE,
                                       'recipient_user_id': recipient, 'channel': 'email', 'state': 'queued'}
    sent = []
    class SMTP:
        async def send(self, **kwargs):
            sent.append(kwargs['idempotency_key'])
            worker._STOP.set()
            return DeliveryResult('dry_run', 1, message_id=kwargs['idempotency_key'])
    monkeypatch.setattr(worker, 'SMTPAdapter', SMTP)
    with pytest.raises(worker.WorkerInterrupted):
        await worker.deliver_pending()
    assert sent == ['first']
    assert state.deliveries['first']['state'] == 'dry_run'
    assert state.deliveries['second']['state'] == 'queued'
