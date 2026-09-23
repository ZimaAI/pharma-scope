"""Validate real endpoint payloads against the shipped OpenAPI 3.1 contract."""
from pathlib import Path
import json
import re
import yaml
import jsonschema
import pytest
from fastapi.testclient import TestClient

from backend import pharma_scope_app as api

SPEC = yaml.safe_load((Path(__file__).resolve().parents[2] / 'docs/reference/PharmaScope_Lite_v1.0/contracts/openapi.yaml').read_text())
P = f'/api/v1/workspaces/{api.DEFAULT_WORKSPACE}'


def assert_contract(response, method, template):
    operation = SPEC['paths'][template][method.lower()]
    status = str(response.status_code)
    assert status in operation['responses'], f'{method} {template}: undocumented {status}'
    schema = operation['responses'][status].get('content', {}).get('application/json', {}).get('schema')
    assert schema, f'{method} {template}: missing response schema'
    document = {**SPEC, **schema}
    errors = list(jsonschema.Draft202012Validator(document, format_checker=jsonschema.FormatChecker()).iter_errors(response.json()))
    assert not errors, f'{method} {template} {status}: ' + '; '.join('/'.join(map(str,e.absolute_path)) + ': ' + e.message for e in errors)
    return response.json()


def template(path):
    matches=[name for name in SPEC['paths'] if re.fullmatch(re.sub(r'\{[^}]+\}', '[^/]+',name),path)]
    assert matches,f'Missing API contract: {path}'
    return min(matches,key=lambda s:s.count('{'))


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('PHARMA_RUNTIME_MODE','replay')
    monkeypatch.setenv('PHARMA_COOKIE_SECURE','0')
    monkeypatch.setattr(api,'state',api.DomainState())
    monkeypatch.setattr(api,'state_store',None)
    monkeypatch.setattr(api,'persistence_error',None)
    with TestClient(api.app) as client: yield client


def call(client,method,path,**kwargs):
    response=client.request(method,path,**kwargs)
    assert response.status_code<400,response.text
    return assert_contract(response,method,template(path))


def login(client,email='analyst@pharmascope.invalid'):
    body=call(client,'POST','/api/v1/auth/login',json={'email':email,'password':'demo'})
    return {'X-CSRF-Token':body['csrf_token']}


@pytest.mark.parametrize('suffix',['dashboard','members','drugs','aliases','entity-links','sources','trials','publications','events','research/runs','reports','subscriptions','inbox','deliveries'])
def test_list_and_dashboard_contracts(client,suffix):
    login(client)
    call(client,'GET',P+'/'+suffix)


def test_snapshot_observation_evidence_and_diff_contracts(client):
    login(client)
    for record in list(api.state.records.values()):
        if record['workspace_id']!=api.DEFAULT_WORKSPACE:continue
        path='trials' if record['kind']=='trial' else 'publications'
        call(client,'GET',P+f'/{path}/{record["id"]}')
        observations=call(client,'GET',P+f'/records/{record["id"]}/observations')['items']
        snapshots=call(client,'GET',P+f'/records/{record["id"]}/snapshots')['items']
        for snapshot in snapshots:call(client,'GET',P+f'/snapshots/{snapshot["id"]}')
        if len(observations)>1:
            call(client,'GET',P+f'/records/{record["id"]}/diff',params={'before_observation_id':observations[0]['id'],'after_observation_id':observations[1]['id']})
    for evidence in api.state.evidence.values():
        if evidence['workspace_id']==api.DEFAULT_WORKSPACE:call(client,'GET',P+f'/evidence/{evidence["id"]}')


def test_report_review_publication_delivery_contracts(client):
    headers=login(client)
    payload=api.read_fixture('07-research-request.json',{})
    run=call(client,'POST',P+'/research/runs',headers=headers,json=payload)
    call(client,'GET',P+f'/research/runs/{run["id"]}')
    call(client,'GET',P+f'/research/runs/{run["id"]}/tool-calls')
    report=call(client,'GET',P+f'/reports/{run["report_id"]}')
    vid=report['current_version_id'];rid=report['id']
    version=call(client,'GET',P+f'/reports/{rid}/versions/{vid}')
    call(client,'GET',P+f'/reports/{rid}/versions/{vid}/claims')
    call(client,'POST',P+f'/reports/{rid}/submit-review',headers=headers,json={})
    headers=login(client,'reviewer@pharmascope.invalid')
    action={'version_id':vid,'content_hash':version['content_hash']}
    call(client,'POST',P+f'/reports/{rid}/reviews',headers=headers,json={**action,'decision':'approve','note':'Contract integration test review'})
    call(client,'POST',P+f'/reports/{rid}/publish',headers=headers,json=action)
    login(client)
    rows=call(client,'GET',P+'/inbox')['items']
    assert rows
    for row in rows:
        call(client,'GET',P+f'/deliveries/{row["id"]}')


def test_sync_and_source_health_job_contracts(client):
    headers=login(client,'admin@pharmascope.invalid')
    payload={'sources':['ctgov'],'drug_ids':api.read_fixture('07-research-request.json',{})['drug_ids'],'mode':'discovery'}
    job=call(client,'POST',P+'/source-syncs',headers=headers,json=payload)
    call(client,'GET',P+f'/jobs/{job["id"]}')
    call(client,'POST',P+'/sources/ctgov/check',headers=headers)


def test_subscription_occurrence_contracts(client):
    headers=login(client)
    payload={'name':'Contract test','drug_ids':api.read_fixture('07-research-request.json',{})['drug_ids'],'source_allowlist':['ctgov'],
             'schedule':{'frequency':'daily','local_time':'09:00','weekday':None,'timezone':'Asia/Shanghai'},'channels':['in_app']}
    sub=call(client,'POST',P+'/subscriptions',headers=headers,json=payload)
    call(client,'GET',P+f'/subscriptions/{sub["id"]}')
    call(client,'POST',P+'/subscriptions/preview',headers=headers,json=payload)
    call(client,'POST',P+f'/subscriptions/{sub["id"]}/trigger',headers=headers)


def test_live_queued_failed_and_usage_contracts(client,monkeypatch):
    headers=login(client)
    monkeypatch.setenv('PHARMA_RUNTIME_MODE','live')
    run=call(client,'POST',P+'/research/runs',headers=headers,json=api.read_fixture('07-research-request.json',{}))
    assert run['runtime_mode']=='live'
    api.state.runs[run['id']].update(status='failed',error_code='MODEL_CONFIGURATION_ERROR',error_message='OPENAI_API_KEY is required',usage={
        'model_calls':0,'tool_calls':0,'records':0,'total_tokens':None,'reserved_tokens':0,'usage_quality':'unknown'})
    call(client,'GET',P+f'/research/runs/{run["id"]}')


def test_registered_business_routes_have_a_contract():
    for route in api.app.routes:
        if route.path.startswith('/api/v1/'):
            assert route.path in SPEC['paths'],route.path
            for method in route.methods-{'HEAD','OPTIONS'}:
                assert method.lower() in SPEC['paths'][route.path],(route.path,method)


def test_runtime_tool_catalog_matches_actual_conductor():
    from backend.research import PharmaResearchConductor
    catalog=json.loads((Path(__file__).resolve().parents[2] / 'docs/reference/PharmaScope_Lite_v1.0/contracts/tool-catalog.json').read_text())
    declared={x['name']:x['input_schema'] for x in catalog['tools']}
    actual={x['function']['name']:x['function']['parameters'] for x in PharmaResearchConductor.tool_definitions()}
    assert declared==actual


def test_live_model_and_checkpoint_sse_events_have_typed_envelopes():
    events=json.loads((Path(__file__).resolve().parents[2] / 'docs/reference/PharmaScope_Lite_v1.0/contracts/event-envelope.schema.json').read_text())
    for i,event in enumerate(['model.started','model.completed','model.failed','researcher.imported','research.checkpoint','run.resumed'],1):
        body={'schema_version':'1.0','run_id':'a48c008c-00cc-47cb-8cc8-2192aba94af5','seq':i,'occurred_at':'2026-09-23T00:00:00Z','type':event,'payload':{}}
        jsonschema.validate(body,events)


def test_offline_transport_live_sync_produces_contract_records_changes_and_audit(client,monkeypatch):
    """Live code path with synthetic source HTTP; no fixture fallback is allowed."""
    import asyncio
    import httpx
    from backend.sources import ClinicalTrialsGovAdapter
    from backend.tests.test_live_adapters import trial
    headers=login(client)
    drug_ids=api.read_fixture('07-research-request.json',{})['drug_ids']
    monkeypatch.setenv('PHARMA_RUNTIME_MODE','live')
    monkeypatch.setattr(api,'read_fixture',lambda *a,**kw:pytest.fail('Live sync read a fixture'))
    count=0
    async def handler(request):
        nonlocal count
        count+=1
        return httpx.Response(200,json={'studies':[trial(10 if count==1 else 20)]})
    class TestTransportAdapter(ClinicalTrialsGovAdapter):
        def __init__(self):super().__init__(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),min_interval=0)
        async def aclose(self):await self._client.aclose()
    monkeypatch.setattr(api,'ClinicalTrialsGovAdapter',TestTransportAdapter)
    payload={'sources':['ctgov'],'drug_ids':drug_ids,'mode':'discovery'}
    for _ in range(2):
        job=call(client,'POST',P+'/source-syncs',headers=headers,json=payload)
        asyncio.run(api._execute_source_sync(job['id'],payload))
        finished=call(client,'GET',P+f'/jobs/{job["id"]}')
        assert finished['state']=='completed' and finished['progress']['processed']==1
    record=next(r for r in api.state.records.values() if r.get('external_id')=='NCT01234567')
    obs=call(client,'GET',P+f'/records/{record["id"]}/observations')['items']
    assert len(obs)==2 and obs[-1]['outcome']=='changed'
    call(client,'GET',P+f'/records/{record["id"]}/snapshots')
    links=call(client,'GET',P+'/entity-links')['items']
    assert any(link['record_id']==record['id'] and link['status']=='pending' for link in links)
    events=call(client,'GET',P+'/events')['items']
    event=next(e for e in events if e['record_id']==record['id'])
    revisions=call(client,'GET',P+f'/events/{event["id"]}/revisions')['items']
    assert revisions and revisions[0]['evidence_ids']
    for eid in revisions[0]['evidence_ids']:call(client,'GET',P+f'/evidence/{eid}')
    api.state.memberships[(api.DEFAULT_WORKSPACE,api.DEFAULT_USER)]['role']='reviewer'
    assert call(client,'GET',P+'/audit')['items']


def test_offline_transport_live_gptr_output_tool_calls_and_sse_contract(client,monkeypatch):
    """Actual GPTR entrypoints and HTTP SDK, with explicitly fake model transport."""
    import asyncio
    import httpx
    from openai import AsyncOpenAI
    from backend.research import PharmaResearchConductor
    from backend.source_ingest import SnapshotIngestor
    from backend.sources import ClinicalTrialsGovAdapter
    from backend.tests.test_live_adapters import trial
    from backend.tests.test_research_runtime import response,report
    headers=login(client)
    drug_ids=api.read_fixture('07-research-request.json',{})['drug_ids']
    monkeypatch.setenv('PHARMA_RUNTIME_MODE','live')
    monkeypatch.setenv('OPENAI_API_KEY','offline-contract-key')
    monkeypatch.setenv('PHARMA_MODEL','test-model')
    monkeypatch.setattr(api,'read_fixture',lambda *a,**kw:pytest.fail('Live research read a fixture'))
    obs=SnapshotIngestor(api.state).ingest(api.DEFAULT_WORKSPACE,ClinicalTrialsGovAdapter()._envelope(trial()),operation_key='offline-test')
    eid=next(e['id'] for e in api.state.evidence.values() if e['snapshot_id']==obs['snapshot_id'])
    link_id=api.uid()
    api.state.links[link_id]={'id':link_id,'workspace_id':api.DEFAULT_WORKSPACE,'record_id':obs['record_id'],'drug_id':drug_ids[0],'status':'approved'}
    calls=0
    async def handler(request):
        nonlocal calls
        calls+=1
        result=response(calls)
        if calls==2:result['choices'][0]['message']['tool_calls'][0]['function']['arguments']=json.dumps({'evidence_ids':[eid]})
        if calls==3:result['choices'][0]['message']['content']=json.dumps(report(eid))
        return httpx.Response(200,json=result)
    async def execute(context):
        async with AsyncOpenAI(api_key='offline-contract-key',http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))) as model:
            return await PharmaResearchConductor(context,model_client=model).run()
    monkeypatch.setattr(api,'execute_live_research',execute)
    payload={'question':'Summarize the authorized clinical trial status and limitations','drug_ids':drug_ids,'source_allowlist':['ctgov'],
             'time_range':{'start':'2020-01-01T00:00:00Z','end_exclusive':'2100-01-01T00:00:00Z','timezone':'UTC'},'budget':{'max_model_calls':3}}
    run=call(client,'POST',P+'/research/runs',headers=headers,json=payload)
    asyncio.run(api._execute_live_run(run['id'],payload))
    completed=call(client,'GET',P+f'/research/runs/{run["id"]}')
    assert completed['status']=='completed',completed
    tools=call(client,'GET',P+f'/research/runs/{run["id"]}/tool-calls')['items']
    assert len(tools)==4 and {x['state'] for x in tools}=={'started','completed'}
    report_body=call(client,'GET',P+f'/reports/{completed["report_id"]}')
    call(client,'GET',P+f'/reports/{report_body["id"]}/versions/{report_body["current_version_id"]}')
    stream=client.get(P+f'/research/runs/{run["id"]}/events')
    assert stream.status_code==200
    schema=json.loads((Path(__file__).resolve().parents[2] / 'docs/reference/PharmaScope_Lite_v1.0/contracts/event-envelope.schema.json').read_text())
    events=[json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith('data: ')]
    assert any(e['type']=='model.completed' for e in events)
    for event in events:jsonschema.validate(event,schema)
