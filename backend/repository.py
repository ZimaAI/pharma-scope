"""Transactional row repository shared by API and the single-slot worker.

PostgreSQL advisory transactions serialize short mutations, never external I/O.
Worker writes merge changed fields against its last read, so unrelated API writes
and cancellation are preserved. Source snapshots/report versions are immutable.
"""
from __future__ import annotations
import copy
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine, select, text, inspect
from sqlalchemy.exc import SQLAlchemyError
from .db import metadata, TABLES, REFS, worker_lease, runtime_meta

class RepositoryUnavailable(RuntimeError): pass
class RepositoryConflict(RuntimeError): pass

LIST_FIELDS = {'audit','notices'}
EVENT_FIELDS = {'run_events','tool_calls'}
LOCK_ID = 746182021

def normalized_url(url):
    for prefix in ('postgres://','postgresql://','postgresql+asyncpg://'):
        if url.startswith(prefix): return 'postgresql+psycopg://' + url[len(prefix):]
    return url

def flatten(payload):
    rows = {}
    for name in TABLES:
        val = payload.get(name, [] if name in LIST_FIELDS or name == 'idempotency' else {})
        if name == 'idempotency':
            items = {json.dumps(v[0], separators=(',',':')): {'key':v[0],'hash':v[1],'response':v[2]} for v in val}
        elif name in LIST_FIELDS:
            items = {v['id']:v for v in val}
        elif name in EVENT_FIELDS:
            items = {}
            for parent, events in val.items():
                for i, event in enumerate(events):
                    item = dict(event, run_id=parent)
                    item.setdefault('seq',i+1)
                    item.setdefault('workspace_id',payload.get('runs',{}).get(parent,{}).get('workspace_id'))
                    items[f'{parent}:{item.get("seq",i+1)}'] = item
        else: items = val
        for key, value in items.items(): rows[(name,str(key))] = copy.deepcopy(value)
    return rows

def unflatten(rows):
    out = {name: [] if name in LIST_FIELDS or name == 'idempotency' else {} for name in TABLES}
    out['schema_version'] = 2
    for (name,key),val in rows.items():
        if name == 'idempotency': out[name].append([val['key'],val['hash'],val['response']])
        elif name in LIST_FIELDS: out[name].append(val)
        elif name in EVENT_FIELDS: out[name].setdefault(val['run_id'],[]).append(val)
        else: out[name][key] = val
    for name in EVENT_FIELDS:
        for items in out[name].values(): items.sort(key=lambda x:x.get('seq',0))
    return out

def merge(base, desired, current):
    if isinstance(base,dict) and isinstance(desired,dict) and isinstance(current,dict):
        result=copy.deepcopy(current)
        for key in set(base)|set(desired):
            if base.get(key) == desired.get(key): continue
            if key not in desired: result.pop(key,None)
            else: result[key]=merge(base.get(key),desired[key],current.get(key))
        # Cancellation wins a simultaneous completion/error save from worker.
        if current.get('status') == 'cancelled':
            result.update(status='cancelled',stop_reason='cancelled',report_id=current.get('report_id'))
        return result
    return copy.deepcopy(desired)

class PersistentStateStore:
    def __init__(self,url,*,echo=False):
        self.url=normalized_url(url)
        self.engine=create_engine(self.url,pool_pre_ping=True,echo=echo,hide_parameters=True)
        if self.engine.dialect.name == 'sqlite':
            from sqlalchemy import event
            @event.listens_for(self.engine,'connect')
            def foreign_keys(connection,record): connection.execute('PRAGMA foreign_keys=ON')
        self.baseline={}
        self.connection=None

    def ensure_schema(self):
        if self.engine.dialect.name == 'sqlite': metadata.create_all(self.engine)
        elif not inspect(self.engine).has_table('pharma_users'):
            raise RepositoryUnavailable('Database migrations required: python -m alembic upgrade head')

    @contextmanager
    def transaction(self):
        if self.connection is not None:
            yield self.connection
            return
        with self.engine.begin() as conn:
            if self.engine.dialect.name == 'postgresql': conn.execute(text('SELECT pg_advisory_xact_lock(:id)'),{'id':LOCK_ID})
            self.connection=conn
            try: yield conn
            finally: self.connection=None

    def _read(self,conn):
        return {(name,row.id):row.payload for name,table in TABLES.items() for row in conn.execute(select(table.c.id,table.c.payload))}

    def load(self):
        self.ensure_schema()
        with self.transaction() as conn:
            rows=self._read(conn)
            if not rows and inspect(conn).has_table('pharmascope_state_checkpoint'):
                old=conn.execute(text('SELECT payload FROM pharmascope_state_checkpoint WHERE id=1')).scalar()
                if old:
                    old=json.loads(old) if isinstance(old,str) else old
                    self.save(old); rows=self._read(conn)
        self.baseline=copy.deepcopy(rows)
        return unflatten(rows) if rows else None

    def save(self,payload):
        self.ensure_schema()
        desired=flatten(payload)
        with self.transaction() as conn:
            current=self._read(conn)
            changed={}
            for key,value in desired.items():
                if key not in self.baseline or value != self.baseline[key]:
                    name,id=key
                    if name in ('snapshots','versions','audit','run_events','tool_calls') and key in self.baseline and key in current and current[key] != value:
                        raise RepositoryConflict(f'{name} are immutable')
                    changed[key]=merge(self.baseline.get(key,{}),value,current.get(key,{}))
            # Events are append-only. An API cancellation and worker event
            # may allocate the same local sequence; allocate the committed seq
            # under the repository transaction instead of overwriting history.
            for (name,id), value in list(changed.items()):
                if name not in EVENT_FIELDS or (name,id) in self.baseline: continue
                run_id=value['run_id']
                if current.get(('runs',run_id),{}).get('status')=='cancelled' and value.get('type') in ('run.completed','report.ready'):
                    changed.pop((name,id)); continue
                if (name,id) in current:
                    seq=max([v.get('seq',0) for (n,k),v in current.items() if n==name and v.get('run_id')==run_id]+[v.get('seq',0) for (n,k),v in changed.items() if n==name and v.get('run_id')==run_id])+1
                    changed.pop((name,id))
                    value=dict(value,seq=seq)
                    changed[(name,f'{run_id}:{seq}')]=value
                if name=='run_events':
                    key=('runs',run_id)
                    row=changed.setdefault(key,copy.deepcopy(current.get(key,desired.get(key,{}))))
                    row['event_seq']=max(row.get('event_seq',0),value['seq'])
                    row['next_event_seq']=row['event_seq']
            for key,value in list(changed.items()):
                if key[0]=='reports' and key not in current and current.get(('runs',value.get('run_id')),{}).get('status')=='cancelled':
                    report_id=key[1]
                    changed.pop(key)
                    for other,v in list(changed.items()):
                        if other[0]=='versions' and v.get('report_id')==report_id: changed.pop(other)
            # Insert parents before children; constraints remain active.
            for table in metadata.sorted_tables:
                name=table.name.removeprefix('pharma_')
                if name not in TABLES: continue
                for (n,id),value in changed.items():
                    if n != name: continue
                    record={'id':id,'payload':value}
                    for col in table.columns:
                        if col.name in record: continue
                        record[col.name]=value.get(col.name)
                    if 'email' in record: record['email']=str(value.get('email',id+'@invalid')).lower()
                    if 'status' in record: record['status']=value.get('status',value.get('state'))
                    if (name,id) in current: conn.execute(table.update().where(table.c.id==id).values(**record))
                    else: conn.execute(table.insert().values(**record))
            for key in set(self.baseline)-set(desired):
                name,id=key
                if name in ('sessions',): conn.execute(TABLES[name].delete().where(TABLES[name].c.id==id))
            self.baseline=copy.deepcopy(desired)

    @contextmanager
    def worker_slot(self):
        # Session lock covers all external I/O, including SMTP. It is distinct
        # from the short API transaction lock and released on process death.
        if self.engine.dialect.name!='postgresql':
            yield True
            return
        with self.engine.connect() as conn:
            acquired=bool(conn.execute(text('SELECT pg_try_advisory_lock(:id)'),{'id':LOCK_ID+1}).scalar())
            conn.commit()
            try: yield acquired
            finally:
                if acquired:
                    conn.execute(text('SELECT pg_advisory_unlock(:id)'),{'id':LOCK_ID+1})
                    conn.commit()

    def claim_worker(self,owner,seconds=30):
        stamp=datetime.now(timezone.utc)
        with self.transaction() as conn:
            row=conn.execute(select(worker_lease).where(worker_lease.c.id=='worker')).mappings().first()
            if row and row['owner'] != owner and row['expires_at'] > stamp.isoformat(): return False
            values=dict(id='worker',owner=owner,heartbeat_at=stamp.isoformat(),expires_at=(stamp+timedelta(seconds=seconds)).isoformat())
            if row: conn.execute(worker_lease.update().where(worker_lease.c.id=='worker').values(**values))
            else: conn.execute(worker_lease.insert().values(**values))
        return True

    def healthy_worker(self,seconds=45):
        with self.engine.connect() as conn:
            row=conn.execute(select(worker_lease.c.heartbeat_at).where(worker_lease.c.id=='worker')).scalar()
        return bool(row and datetime.fromisoformat(row)>datetime.now(timezone.utc)-timedelta(seconds=seconds))

def state_payload(state: Any) -> dict[str, Any]:
    """Serialize DomainState without locks or transient SQL sessions."""
    fields = (
        "users", "workspaces", "memberships", "sessions", "drugs", "aliases", "links",
        "records", "snapshots", "observations", "evidence", "events", "revisions", "jobs",
        "runs", "run_events", "tool_calls", "reports", "versions", "reviews", "subscriptions",
        "occurrences", "deliveries", "audit", "notices", "idempotency", "sources",
    )
    out: dict[str, Any] = {"schema_version": 1}
    for field in fields:
        value = getattr(state, field, {})
        if field == "idempotency":
            # tuple keys/values are not JSON objects; encode an explicit list.
            out[field] = [[list(k), v[0], v[1]] for k, v in value.items()]
        elif isinstance(value, dict):
            # tuple membership keys need conversion to stable string/list keys.
            encoded: dict[str, Any] = {}
            for key, item in value.items():
                stable = "|".join(key) if isinstance(key, tuple) else str(key)
                encoded[stable] = item
            out[field] = encoded
        else:
            out[field] = value
    return out


def restore_state(state: Any, payload: dict[str, Any]) -> None:
    """Restore a checkpoint while retaining the DomainState lock object."""
    for field in (
        "users", "workspaces", "drugs", "aliases", "links", "records", "snapshots", "observations",
        "evidence", "events", "revisions", "jobs", "runs", "reports", "versions", "reviews",
        "subscriptions", "occurrences", "deliveries", "sources",
    ):
        raw = payload.get(field)
        if isinstance(raw, dict):
            setattr(state, field, raw)
    for field in ("run_events", "tool_calls"):
        raw = payload.get(field)
        if isinstance(raw, dict):
            setattr(state, field, raw)
    for field in ("audit", "notices"):
        raw = payload.get(field)
        if isinstance(raw, list):
            setattr(state, field, raw)
    raw = payload.get("memberships")
    if isinstance(raw, dict):
        state.memberships = {}
        for key, val in raw.items():
            if "|" in key:
                ws, uid = key.split("|", 1)
                state.memberships[(ws, uid)] = val
    raw = payload.get("sessions")
    if isinstance(raw, dict):
        state.sessions = raw
    raw = payload.get("idempotency")
    if isinstance(raw, list):
        state.idempotency = {}
        for item in raw:
            if isinstance(item, list) and len(item) == 3:
                state.idempotency[tuple(item[0])] = (item[1], item[2])



def repository_from_env():
    url=os.getenv('PHARMA_DATABASE_URL') or os.getenv('DATABASE_URL')
    mode=os.getenv('PHARMA_RUNTIME_MODE','live')
    if mode not in ('replay','demo','live','gptr'): raise RepositoryUnavailable('PHARMA_RUNTIME_MODE must be live or replay')
    if not url:
        if mode in ('live','gptr'): raise RepositoryUnavailable('PHARMA_DATABASE_URL is required in live mode')
        return None
    if mode in ('live','gptr') and not normalized_url(url).startswith('postgresql+'):
        raise RepositoryUnavailable('live mode requires PostgreSQL')
    store=PersistentStateStore(url)
    store.ensure_schema()
    selected='replay' if mode in ('replay','demo') else 'live'
    with store.transaction() as conn:
        saved=conn.execute(select(runtime_meta.c.mode).where(runtime_meta.c.id==1)).scalar()
        if saved and saved != selected: raise RepositoryUnavailable('Database runtime mode differs; use a separate live/demo database')
        if not saved:
            # Old checkpoint imports must never promote fictional data to live.
            if selected=='live':
                records=store._read(conn)
                if any(v.get('is_demo') or v.get('runtime_mode')=='replay' for v in records.values()):
                    raise RepositoryUnavailable('Replay data cannot be opened in live mode')
                if inspect(conn).has_table('pharmascope_state_checkpoint'):
                    old=conn.execute(text('SELECT payload FROM pharmascope_state_checkpoint WHERE id=1')).scalar()
                    if old and ('DEMO' in json.dumps(old) or 'replay' in json.dumps(old)):
                        raise RepositoryUnavailable('Replay checkpoint cannot be imported in live mode')
            conn.execute(runtime_meta.insert().values(id=1,mode=selected))
    return store
