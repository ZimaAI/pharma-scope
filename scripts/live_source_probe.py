#!/usr/bin/env python3
"""Real public-source → worker → PostgreSQL probe in a disposable schema.

Requires a test-only PostgreSQL URL. Never reads demo fixtures or calls a model.
NCBI identity is never synthesized: missing email is recorded as a blocker.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url
from backend.tests.test_postgres_integration import api_process, command, login

url=os.environ['PHARMA_TEST_DATABASE_URL']
engine=create_engine(url)
schema='pharmascope_source_probe_'+uuid.uuid4().hex
with engine.begin() as conn: conn.execute(text(f'CREATE SCHEMA "{schema}"'))
private=make_url(url).update_query_dict({'options':'-csearch_path='+schema}).render_as_string(hide_password=False)
env=dict(os.environ,PHARMA_DATABASE_URL=private,DATABASE_URL=private,PHARMA_RUNTIME_MODE='live',PHARMA_ADMIN_PASSWORD='temporary-test-password-'+uuid.uuid4().hex,PHARMA_COOKIE_SECURE='0',PHARMA_ALLOW_DEV_HEADER='0',PH_REAL_EMAIL_ENABLED='false',PH_SMTP_DRY_RUN='true',PHARMA_SOURCE_TIMEOUT='15',PHARMA_SOURCE_RETRIES='1')
result={'mode':'live','schema':'isolated test schema','model':'NOT_REQUESTED'}
worker=None
try:
    command(env,'-m','alembic','upgrade','head')
    command(env,'-m','backend.cli','init','--email','integration@pharmascope.invalid','--workspace-name','Live source probe')
    with tempfile.TemporaryDirectory(prefix='pharmascope-source-') as directory:
        with api_process(env,Path(directory)) as origin, httpx.Client(base_url=origin,trust_env=False,timeout=20) as client:
            ws=login(client,env)
            path=f'/api/v1/workspaces/{ws}'
            created=client.post(path+'/drugs',json={'display_name':'pembrolizumab'})
            created.raise_for_status()
            job=client.post(path+'/source-syncs',headers={'Idempotency-Key':'real-source-probe'},json={'sources':['ctgov','pubmed'],'drug_ids':[created.json()['id']],'mode':'discovery','limit':1})
            job.raise_for_status();job_id=job.json()['id']
            with open(Path(directory)/'worker.log','w') as log:
                worker=subprocess.Popen([sys.executable,'-m','backend.worker'],env=env,stdout=log,stderr=log)
                for _ in range(120):
                    value=client.get(path+'/jobs/'+job_id).json()
                    if value.get('state') in ('completed','partial','failed'):break
                    time.sleep(.5)
                else: raise RuntimeError('Source job did not finish in 60 seconds')
                result['job']=value
                trials=client.get(path+'/trials').json()['items']
                result['trial_ids']=[r['external_id'] for r in trials]
                result['snapshots']=[]
                for trial in trials:
                    snapshots=client.get(path+'/records/'+trial['id']+'/snapshots').json()['items']
                    result['snapshots'] += [{'content_hash':s['content_hash'],'source_updated':s.get('source_updated'),'fetched_at':s.get('first_observed_at')} for s in snapshots]
                result['pending_links']=len(client.get(path+'/entity-links?status=pending').json()['items'])
                assert result['job']['state'] in ('completed','partial','failed')
                assert all(x.get('limitations') for x in value['coverage'] if x['status']=='failed')
                worker.terminate();worker.wait(timeout=10);worker=None
finally:
    if worker:
        worker.terminate();worker.wait(timeout=10)
    with engine.begin() as conn: conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    engine.dispose()
output=Path('outputs/live-source-integration.json');output.parent.mkdir(exist_ok=True)
output.write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False,indent=2))
