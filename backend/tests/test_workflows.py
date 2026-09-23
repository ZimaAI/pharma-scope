import asyncio
import copy
import json
import os
import pytest
from fastapi.testclient import TestClient
from backend import pharma_scope_app as api
from backend.repository import PersistentStateStore, state_payload, restore_state, RepositoryConflict
from backend.auth import hash_password,verify_password

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('PHARMA_RUNTIME_MODE','replay')
    monkeypatch.setenv('PHARMA_COOKIE_SECURE','0')
    monkeypatch.setattr(api,'state',api.DomainState())
    monkeypatch.setattr(api,'state_store',None)
    monkeypatch.setattr(api,'persistence_error',None)
    with TestClient(api.app) as client: yield client


def login(client,email='analyst@pharmascope.invalid'):
    response=client.post('/api/v1/auth/login',json={'email':email,'password':'demo'})
    assert response.status_code==200,response.text
    return {'X-CSRF-Token':response.json()['csrf_token']}


def run_payload():
    return api.read_fixture('07-research-request.json',{})

P=f'/api/v1/workspaces/{api.DEFAULT_WORKSPACE}'


def test_review_publish_version_hash_notifications(client):
    headers=login(client)
    run=client.post(P+'/research/runs',json=run_payload(),headers=headers).json()
    rid=run['report_id'];report=api.state.reports[rid];version=api.state.versions[report['current_version_id']]
    submit=client.post(P+f'/reports/{rid}/submit-review',headers=headers,json={})
    assert submit.status_code==200,submit.text
    # Original initiator cannot self review, even after role promotion/edit.
    api.state.memberships[(api.DEFAULT_WORKSPACE,api.DEFAULT_USER)]['role']='reviewer'
    payload={'version_id':version['id'],'content_hash':version['content_hash'],'decision':'approve','note':'Checked evidence'}
    own=client.post(P+f'/reports/{rid}/reviews',headers=headers,json=payload)
    assert own.status_code==409 and own.json()['error']['code']=='SELF_REVIEW_FORBIDDEN'
    headers=login(client,'reviewer@pharmascope.invalid')
    bad=client.post(P+f'/reports/{rid}/reviews',headers=headers,json={**payload,'content_hash':'wrong'})
    assert bad.status_code==409
    reviewed=client.post(P+f'/reports/{rid}/reviews',headers=headers,json=payload)
    assert reviewed.status_code==201,reviewed.text
    body={'version_id':version['id'],'content_hash':version['content_hash']}
    published=client.post(P+f'/reports/{rid}/publish',headers={**headers,'Idempotency-Key':'publish-1'},json=body)
    assert published.status_code==200,published.text
    count=len(api.state.deliveries)
    duplicate=client.post(P+f'/reports/{rid}/publish',headers={**headers,'Idempotency-Key':'publish-1'},json=body)
    assert duplicate.status_code==200 and len(api.state.deliveries)==count
    headers=login(client)
    inbox=client.get(P+'/inbox').json()['items'];assert any(d['report_id']==rid for d in inbox)
    assert api.state.audit
    original=copy.deepcopy(version)
    updated=client.post(P+f'/reports/{rid}/versions',headers=headers,json={'base_version_id':version['id'],'edit_note':'Updated','content':version['content']})
    assert updated.status_code==201,updated.text
    assert api.state.versions[version['id']]==original
    headers=login(client,'reviewer@pharmascope.invalid')
    stale=client.post(P+f'/reports/{rid}/publish',headers=headers,json=body)
    assert stale.status_code==409


def test_reader_cannot_export_other_report_draft_or_review(client):
    headers=login(client)
    run=client.post(P+'/research/runs',json=run_payload(),headers=headers).json()
    api.state.memberships[(api.DEFAULT_WORKSPACE,api.DEFAULT_USER)]['role']='reader'
    rid=run['report_id'];vid=api.state.reports[rid]['current_version_id']
    assert client.get(P+f'/reports/{rid}/export').status_code==404
    assert client.get(P+f'/reports/{rid}/versions/{vid}').status_code==404
    assert client.post(P+'/drugs',json={'display_name':'Denied'},headers=headers).status_code==403


def test_foreign_reference_idempotency_and_csrf(client):
    headers=login(client)
    foreign='foreign-drug';api.state.drugs[foreign]={'id':foreign,'workspace_id':api.SECOND_WORKSPACE}
    for path,body in [('/research/runs',{**run_payload(),'drug_ids':[foreign]}),('/source-syncs',{'drug_ids':[foreign],'sources':['ctgov'],'mode':'discovery'})]:
        assert client.post(P+path,json=body,headers=headers).status_code==404
    payload=run_payload()
    first=client.post(P+'/research/runs',json=payload,headers={**headers,'Idempotency-Key':'same'})
    second=client.post(P+'/research/runs',json=payload,headers={**headers,'Idempotency-Key':'same'})
    assert first.json()['id']==second.json()['id']
    assert client.post(P+'/research/runs',json={**payload,'question':'Changed question sufficiently long'},headers={**headers,'Idempotency-Key':'same'}).status_code==409
    assert client.post('/api/v1/auth/logout').status_code==403
    assert client.post('/api/v1/auth/logout',headers=headers).status_code==200
    assert client.get('/api/v1/auth/me').status_code==401


def test_live_auth_does_not_accept_demo_password_or_dev_header(client,monkeypatch):
    monkeypatch.setenv('PHARMA_RUNTIME_MODE','live')
    assert client.post('/api/v1/auth/login',json={'email':'analyst@pharmascope.invalid','password':'demo'}).status_code==401
    assert client.get('/api/v1/auth/me',headers={'X-User-Id':api.DEFAULT_USER}).status_code==401
    user=api.state.users[api.DEFAULT_USER];user['password_hash']=hash_password('long-test-password')
    response=client.post('/api/v1/auth/login',json={'email':user['email'],'password':'long-test-password'})
    assert response.status_code==200 and 'password_hash' not in response.text


def test_subscription_timezone_owner_and_worker_queue(client):
    headers=login(client)
    payload={'name':'Monitor','drug_ids':run_payload()['drug_ids'],'source_allowlist':['ctgov'],'schedule':{'frequency':'weekly','weekday':1,'timezone':'America/New_York','local_time':'09:00'},'channels':['in_app']}
    preview=client.post(P+'/subscriptions/preview',json=payload,headers=headers)
    assert preview.status_code==200 and len(preview.json()['occurrences'])==5
    invalid=client.post(P+'/subscriptions/preview',json={**payload,'schedule':{**payload['schedule'],'weekday':99}},headers=headers)
    assert invalid.status_code==422
    result=client.post(P+'/subscriptions',json=payload,headers=headers);assert result.status_code==201,result.text
    sid=result.json()['id']
    trigger=client.post(P+f'/subscriptions/{sid}/trigger',headers={**headers,'Idempotency-Key':'sub-1'})
    assert trigger.status_code==202
    again=client.post(P+f'/subscriptions/{sid}/trigger',headers={**headers,'Idempotency-Key':'sub-1'})
    assert again.json()['id']==trigger.json()['id']
    login(client,'reviewer@pharmascope.invalid')
    assert client.get(P+f'/subscriptions/{sid}').status_code==404
    from backend import worker
    asyncio.run(worker.run_once())
    assert api.state.occurrences[trigger.json()['id']]['state']=='no_change'


def test_repository_merges_unrelated_changes_and_cancel_wins(tmp_path,monkeypatch):
    monkeypatch.setenv('PHARMA_RUNTIME_MODE','replay')
    state=api.DomainState();url=f'sqlite:///{tmp_path}/repo.db'
    one=PersistentStateStore(url);one.save(state_payload(state))
    two=PersistentStateStore(url);a=one.load();b=two.load()
    run_id=next(iter(a['runs']))
    a['runs'][run_id]['status']='cancelled';one.save(a)
    b['runs'][run_id]['status']='failed';b['runs'][run_id]['error_code']='upstream';two.save(b)
    assert one.load()['runs'][run_id]['status']=='cancelled'
    new=api.uid();b['drugs'][new]={'id':new,'workspace_id':api.DEFAULT_WORKSPACE,'display_name':'persist'};two.save(b)
    assert one.load()['runs'][run_id]['status']=='cancelled'
    bad=one.load();vid=next(iter(bad['versions']));bad['versions'][vid]['content_hash']='mutated'
    with pytest.raises(RepositoryConflict): one.save(bad)


def test_sse_replay_resume_and_live_cancel_retry(client,monkeypatch):
    headers=login(client)
    demo=client.post(P+'/research/runs',json=run_payload(),headers=headers).json()
    stream=client.get(P+f'/research/runs/{demo["id"]}/events',headers={'Last-Event-ID':'1'})
    assert stream.status_code==200 and 'id: 1\n' not in stream.text and 'run.completed' in stream.text
    monkeypatch.setenv('PHARMA_RUNTIME_MODE','live')
    created=client.post(P+'/research/runs',json=run_payload(),headers=headers).json()
    assert created['status']=='queued'
    cancelled=client.post(P+f'/research/runs/{created["id"]}/cancel',headers=headers)
    assert cancelled.json()['status']=='cancelled'
    retry=client.post(P+f'/research/runs/{created["id"]}/retry',headers=headers,json={})
    assert retry.status_code==202 and retry.json()['id']!=created['id']


def test_concurrent_event_appends_never_overwrite_cancellation(tmp_path,monkeypatch):
    monkeypatch.setenv('PHARMA_RUNTIME_MODE','replay')
    initial=api.DomainState();url=f'sqlite:///{tmp_path}/events.db'
    one=PersistentStateStore(url);one.save(state_payload(initial));two=PersistentStateStore(url)
    a=one.load();b=two.load();rid=next(iter(a['runs']))
    seq=max(e['seq'] for e in a['run_events'][rid])+1
    a['run_events'][rid].append({'run_id':rid,'seq':seq,'type':'run.cancelled','payload':{},'workspace_id':api.DEFAULT_WORKSPACE})
    b['run_events'][rid].append({'run_id':rid,'seq':seq,'type':'model.completed','payload':{'usage':{}},'workspace_id':api.DEFAULT_WORKSPACE})
    one.save(a);two.save(b)
    events=one.load()['run_events'][rid]
    assert events[-2]['type']=='run.cancelled' and events[-1]['type']=='model.completed'
    assert events[-1]['seq']>events[-2]['seq']
    # Repeating worker checkpoint cannot append duplicate events.
    two.save(b)
    assert len(one.load()['run_events'][rid])==len(events)


def test_cancelled_run_cannot_commit_a_report_from_stale_worker(tmp_path,monkeypatch):
    monkeypatch.setenv('PHARMA_RUNTIME_MODE','replay')
    initial=api.DomainState();rid=api.uid()
    initial.runs[rid]={'id':rid,'workspace_id':api.DEFAULT_WORKSPACE,'status':'running','report_id':None,'event_seq':0}
    initial.run_events[rid]=[]
    url=f'sqlite:///{tmp_path}/cancel-report.db';one=PersistentStateStore(url);one.save(state_payload(initial));two=PersistentStateStore(url)
    a=one.load();b=two.load();a['runs'][rid]['status']='cancelled';one.save(a)
    report,version=api.uid(),api.uid()
    b['runs'][rid].update(status='completed',report_id=report)
    b['reports'][report]={'id':report,'workspace_id':api.DEFAULT_WORKSPACE,'run_id':rid}
    b['versions'][version]={'id':version,'workspace_id':api.DEFAULT_WORKSPACE,'report_id':report,'version_no':1}
    b['run_events'].setdefault(rid,[]).append({'run_id':rid,'seq':1,'workspace_id':api.DEFAULT_WORKSPACE,'type':'report.ready','payload':{'report_id':report}})
    two.save(b)
    result=one.load()
    assert result['runs'][rid]['status']=='cancelled' and result['runs'][rid]['report_id'] is None
    assert report not in result['reports'] and version not in result['versions']
    assert result['run_events'].get(rid,[])==[]


def test_revoked_run_owner_never_calls_model(client,monkeypatch):
    headers=login(client);monkeypatch.setenv('PHARMA_RUNTIME_MODE','live')
    run=client.post(P+'/research/runs',json=run_payload(),headers=headers).json()
    api.state.memberships[(api.DEFAULT_WORKSPACE,api.DEFAULT_USER)]['enabled']=False
    async def forbidden(_): raise AssertionError('model must not execute for revoked member')
    monkeypatch.setattr(api,'execute_live_research',forbidden)
    asyncio.run(api._execute_live_run(run['id'],run_payload()))
    assert api.state.runs[run['id']]['error_code']=='OWNER_PERMISSION_REVOKED'
    assert api.state.runs[run['id']]['report_id'] is None


def test_refresh_linked_preserves_success_when_another_record_fails(client,monkeypatch):
    from backend.sources import SourceEnvelope,SourceError
    monkeypatch.setenv('PHARMA_RUNTIME_MODE','live')
    drug=run_payload()['drug_ids'][0];ids=[api.uid(),api.uid()]
    for index,id in enumerate(ids):
        api.state.records[id]={'id':id,'workspace_id':api.DEFAULT_WORKSPACE,'source':'ctgov','external_id':f'NCT0000000{index}','kind':'trial','current_snapshot_id':None}
        api.state.links[api.uid()]={'workspace_id':api.DEFAULT_WORKSPACE,'record_id':id,'drug_id':drug,'status':'approved'}
    class Adapter:
        async def fetch(self,external_id):
            if external_id.endswith('1'):raise SourceError('timeout','Explicit offline contract timeout')
            return SourceEnvelope(source='ctgov',external_id=external_id,raw_payload={'contract_test':True},normalized={'title':'Offline contract record'},source_updated={'value':None,'precision':'unknown','kind':'source_reported'},fetched_at=api.now(),content_hash='b'*64)
        async def aclose(self):pass
    monkeypatch.setattr(api,'ClinicalTrialsGovAdapter',Adapter)
    job_id=api.uid();payload={'mode':'refresh_linked','drug_ids':[drug],'sources':['ctgov']}
    api.state.jobs[job_id]={'id':job_id,'workspace_id':api.DEFAULT_WORKSPACE,'kind':'ingest','state':'queued','attempt':0}
    asyncio.run(api._execute_source_sync(job_id,payload))
    assert api.state.jobs[job_id]['state']=='partial'
    assert api.state.records[ids[0]]['current_snapshot_id'] in api.state.snapshots
    assert any(o['record_id']==ids[1] and o['outcome']=='failed' for o in api.state.observations.values())
    assert api.sources_for(api.DEFAULT_WORKSPACE)['ctgov']['state']=='degraded'
