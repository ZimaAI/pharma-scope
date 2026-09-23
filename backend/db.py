"""Relational persistence schema. JSON retains versioned source/contract payloads.

Every business object has an indexed workspace and database enforced ownership;
large immutable snapshots live in separate rows, not in a global checkpoint.
"""
from sqlalchemy import MetaData, Table, Column, String, JSON, Integer, ForeignKeyConstraint, UniqueConstraint, Index

metadata = MetaData()
COLLECTIONS = ('users','workspaces','memberships','sessions','drugs','aliases','records','snapshots','observations','evidence','links','events','revisions','jobs','runs','run_events','tool_calls','reports','versions','reviews','subscriptions','occurrences','deliveries','audit','notices','idempotency','sources')
REFS = {
 'memberships': {'user_id':'users'}, 'sessions': {'user_id':'users'},
 'aliases': {'drug_id':'drugs'}, 'snapshots': {'record_id':'records'},
 'observations': {'record_id':'records','snapshot_id':'snapshots'},
 'evidence': {'snapshot_id':'snapshots'}, 'links': {'record_id':'records','drug_id':'drugs'},
 'revisions': {'event_id':'events'}, 'run_events': {'run_id':'runs'},
 'tool_calls': {'run_id':'runs'}, 'reports': {'run_id':'runs'},
 'versions': {'report_id':'reports'}, 'reviews': {'report_id':'reports','version_id':'versions'},
 'occurrences': {'subscription_id':'subscriptions'},
 'deliveries': {'recipient_user_id':'users'},
}
TABLES = {}
for name in COLLECTIONS:
    cols = [Column('id', String(512), primary_key=True), Column('payload', JSON, nullable=False)]
    scoped = name not in ('users','workspaces','sessions','idempotency','sources')
    if scoped:
        cols += [Column('workspace_id', String(512), nullable=False),
                 ForeignKeyConstraint(['workspace_id'], ['pharma_workspaces.id']),
                 UniqueConstraint('workspace_id','id'), Index(f'ix_pharma_{name}_workspace','workspace_id')]
    for field, target in REFS.get(name, {}).items():
        cols.append(Column(field, String(512), nullable=True))
        if scoped and target not in ('users','workspaces'):
            cols.append(ForeignKeyConstraint(['workspace_id',field], [f'pharma_{target}.workspace_id',f'pharma_{target}.id']))
        else:
            cols.append(ForeignKeyConstraint([field], [f'pharma_{target}.id']))
        cols.append(Index(f'ix_pharma_{name}_{field}', field))
    if name == 'users':
        cols += [Column('email', String(320), nullable=False, unique=True)]
    if name == 'records':
        cols += [Column('source',String(30)),Column('external_id',String(200)),UniqueConstraint('workspace_id','source','external_id')]
    if name == 'snapshots':
        cols += [Column('content_hash',String(64)),UniqueConstraint('workspace_id','record_id','content_hash')]
    if name in ('observations','run_events'):
        seq = 'observation_seq' if name == 'observations' else 'seq'
        parent = 'record_id' if name == 'observations' else 'run_id'
        cols += [Column(seq,Integer,nullable=False),UniqueConstraint('workspace_id',parent,seq)]
    if name == 'versions':
        cols += [Column('version_no',Integer,nullable=False),UniqueConstraint('workspace_id','report_id','version_no')]
    if name == 'occurrences':
        cols += [Column('scheduled_at',String(50)),UniqueConstraint('workspace_id','subscription_id','scheduled_at')]
    if name in ('jobs','runs','deliveries','subscriptions'):
        cols += [Column('status',String(40)),Index(f'ix_pharma_{name}_status','status')]
    TABLES[name] = Table('pharma_' + name, metadata, *cols)

worker_lease = Table('pharma_worker_lease', metadata,
    Column('id',String(50),primary_key=True),Column('owner',String(100),nullable=False),
    Column('expires_at',String(50),nullable=False),Column('heartbeat_at',String(50),nullable=False))
class Base:
    metadata = metadata

runtime_meta = Table('pharma_runtime', metadata, Column('id',Integer,primary_key=True),Column('mode',String(20),nullable=False))
