"""Credential-safe live import/source/model verification; never reads fixtures.

python -m backend.live_probe --sources [--model] [--output /path/result.json]
Model verification requires real OPENAI_API_KEY/PHARMA_MODEL credentials and a
successful source fetch. It incurs bounded model requests when explicitly used.
"""
from __future__ import annotations
import argparse
import asyncio
import json
import os
import resource
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .gptr_adapter import PharmaResearchConductor as Probe
from .research import ResearchBudget, ResearchContext, execute_live_research
from .sources import ClinicalTrialsGovAdapter, PubMedAdapter, SourceError, SourceQuery


async def probe(args) -> dict:
    os.environ['PHARMA_RUNTIME_MODE'] = 'live'
    result = {'checked_at': datetime.now(timezone.utc).isoformat(), 'mode': 'live', 'gptr': Probe.probe(), 'sources': {}, 'model_execution': {'status': 'NOT_RUN'}}
    evidence = []
    if args.sources or args.model:
        for source, factory in [('ctgov', ClinicalTrialsGovAdapter), ('pubmed', PubMedAdapter)]:
            adapter = None
            started = time.monotonic()
            try:
                adapter = factory(timeout=15, max_attempts=1)
                page = await adapter.search(SourceQuery('pembrolizumab', limit=1))
                result['sources'][source] = {'status': 'PASS', 'records': len(page.items), 'next_cursor': bool(page.next_cursor), 'elapsed_seconds': round(time.monotonic()-started, 3),
                    'samples': [{'external_id': x.external_id, 'content_hash': x.content_hash, 'fetched_at': x.fetched_at, 'source_updated': x.source_updated} for x in page.items]}
                evidence.extend({'evidence_id': str(uuid.uuid4()), 'workspace_id': '4dc89490-55ef-4249-af76-4829deed875a', 'source': item.source, 'normalized': item.normalized, 'is_demo': False} for item in page.items)
            except SourceError as exc:
                result['sources'][source] = {'status': 'BLOCKED', 'error_code': exc.code, 'message': str(exc), 'elapsed_seconds': round(time.monotonic()-started, 3)}
            finally:
                if adapter:
                    await adapter.aclose()
    if args.model:
        if not result['gptr'].get('configured'):
            result['model_execution'] = {'status': 'BLOCKED', 'error_code': result['gptr'].get('error_code'), 'message': result['gptr'].get('message')}
        elif not evidence:
            result['model_execution'] = {'status': 'BLOCKED', 'error_code': 'NO_REAL_SOURCE_EVIDENCE'}
        else:
            events = []
            context = ResearchContext(workspace_id='4dc89490-55ef-4249-af76-4829deed875a', run_id=str(uuid.uuid4()),
                question='Summarize the stored source metadata and its limitations. Search and read authorized evidence before writing. Do not infer efficacy or approval.',
                source_allowlist=list(dict.fromkeys(e['source'] for e in evidence)), drug_ids=['62953f8a-f39b-4569-91ab-c8fd34490b8a'],
                time_range={'start':'2000-01-01T00:00:00Z','end_exclusive':datetime.now(timezone.utc).isoformat(),'timezone':'UTC'},
                budget=ResearchBudget(max_model_calls=5,max_tool_calls=5,max_records=2,timeout_seconds=90), evidence=evidence,
                emit=lambda typ,payload: events.append({'type':typ,'usage':payload.get('usage')}))
            try:
                output=await execute_live_research(context)
                result['model_execution']={'status':'PASS','usage':output['usage'],'claims':len(output['claims']),'events':events}
            except Exception as exc:
                result['model_execution']={'status':'BLOCKED','error_code':getattr(exc,'code','MODEL_EXECUTION_FAILED'),'message':str(exc),'events':events}
    result['max_rss_kib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return result


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources',action='store_true')
    parser.add_argument('--model',action='store_true')
    parser.add_argument('--output')
    args=parser.parse_args()
    result=asyncio.run(probe(args))
    rendered=json.dumps(result,ensure_ascii=False,indent=2)
    if args.output:
        Path(args.output).write_text(rendered+'\n')
    print(rendered)
    return 0 if result['gptr'].get('imported') and all(x['status']=='PASS' for x in result['sources'].values()) and (not args.model or result['model_execution']['status']=='PASS') else 1


if __name__ == '__main__':
    raise SystemExit(main())
