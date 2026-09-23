"""Offline HTTP contract tests; payloads are explicitly synthetic test data."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import jsonschema
import pytest

from backend.sources import ClinicalTrialsGovAdapter, PubMedAdapter, SourceQuery, SourceError, SourceEnvelope, stable_hash
from backend.source_ingest import SnapshotIngestor

SCHEMA = json.loads((Path(__file__).resolve().parents[2] / 'docs/reference/PharmaScope_Lite_v1.0/contracts/source-snapshot.schema.json').read_text())


def trial(enrollment=10, **extra):
    return {"protocolSection": {"identificationModule": {"nctId": "NCT01234567", "briefTitle": "Synthetic contract-test study"}, "statusModule": {"overallStatus": "RECRUITING", "lastUpdatePostDateStruct": {"date": "2026-09"}}, "designModule": {"phases": ["PHASE2"], "enrollmentInfo": {"count": enrollment, "type": "ESTIMATED"}}}, "hasResults": False, **extra}


XML = '''<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>12345678</PMID><DateRevised><Year>2026</Year><Month>9</Month><Day>1</Day></DateRevised><Article><Journal><JournalIssue><PubDate><Year>2026</Year><Month>Sep</Month></PubDate></JournalIssue><Title>Test Journal</Title></Journal><ArticleTitle>A <i>synthetic</i> study</ArticleTitle><Abstract><AbstractText Label="METHODS">Test <b>abstract</b>.</AbstractText></Abstract><AuthorList><Author><LastName>Tester</LastName><ForeName>A</ForeName></Author></AuthorList><PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList></Article><CommentsCorrectionsList><CommentsCorrections RefType="ErratumIn"><PMID>87654321</PMID></CommentsCorrections></CommentsCorrectionsList></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">10.0000/test</ArticleId></ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>'''


def empty_state():
    return SimpleNamespace(records={}, snapshots={}, observations={}, evidence={}, events={}, revisions={})


def test_ctgov_contract_and_source_snapshot_schema():
    async def run():
        async def handler(request):
            assert '2026-09-01' in request.url.params['filter.advanced']
            return httpx.Response(200, json={"studies": [trial()], "nextPageToken": "next"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = ClinicalTrialsGovAdapter(client=client, min_interval=0)
            page = await adapter.search(SourceQuery("test", since="2026-09-01T00:00:00Z"))
            assert page.next_cursor == "next" and page.items[0].external_id == "NCT01234567"
            state = empty_state()
            observation = SnapshotIngestor(state).ingest("89e5b360-8ae4-4e07-9986-ac21d469208e", page.items[0], operation_key="test")
            snapshot = state.snapshots[observation['snapshot_id']]
            jsonschema.validate(snapshot, SCHEMA)
            assert snapshot['source_updated']['precision'] == 'month'
    asyncio.run(run())


def test_pubmed_search_fetches_xml_abstracts_and_preserves_partial_dates(monkeypatch):
    monkeypatch.setenv('PHARMA_RUNTIME_MODE', 'live')
    async def run():
        requests = []
        async def handler(request):
            requests.append(request)
            assert request.url.params['email'] == 'contract@example.invalid'
            assert request.url.params['api_key'] == 'test-key'
            if request.url.path.endswith('esearch.fcgi'):
                return httpx.Response(200, json={'esearchresult': {'idlist': ['12345678'], 'count': '2'}})
            assert request.url.params['retmode'] == 'xml'
            return httpx.Response(200, text=XML)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            page = await PubMedAdapter(client=client, email='contract@example.invalid', api_key='test-key', min_interval=0).search(SourceQuery('test'))
        envelope = page.items[0]
        assert page.next_cursor == '1' and len(requests) == 2
        assert envelope.normalized['title'] == 'A synthetic study'
        assert envelope.normalized['abstract_text'] == 'METHODS: Test abstract.'
        assert envelope.normalized['publication_date']['value'] == '2026-09'
        assert envelope.source_updated['value'] == '2026-09-01'
        assert envelope.normalized['correction_relations'] == [{'relation': 'ErratumIn', 'external_id': '87654321'}]
        state = empty_state()
        obs = SnapshotIngestor(state).ingest('89e5b360-8ae4-4e07-9986-ac21d469208e', envelope, operation_key='xml')
        jsonschema.validate(state.snapshots[obs['snapshot_id']], SCHEMA)
    asyncio.run(run())


@pytest.mark.parametrize('source,body', [('ctgov', {}), ('pubmed', {'esearchresult': {'count': '1', 'idlist': [], 'errorlist': {'phrasesnotfound': ['x']}}})])
def test_malformed_success_is_not_zero_results(source, body):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))) as client:
            adapter = ClinicalTrialsGovAdapter(client=client, min_interval=0) if source == 'ctgov' else PubMedAdapter(client=client, email='contract@example.invalid', min_interval=0)
            with pytest.raises(SourceError, match='invalid'):
                await adapter.search(SourceQuery('test'))
    asyncio.run(run())


def test_pubmed_failure_is_structured_and_retry_after_respected():
    async def run():
        calls = []
        async def handler(request):
            calls.append(request)
            return httpx.Response(429, headers={'Retry-After': '120'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = PubMedAdapter(client=client, email='contract@example.invalid', min_interval=0, timeout=.1, max_attempts=3)
            with pytest.raises(SourceError) as info:
                await adapter.search(SourceQuery('test'))
            assert info.value.code == 'rate_limited' and len(calls) == 1
    asyncio.run(run())


def test_source_retry_succeeds_and_payload_size_is_bounded():
    async def run():
        calls = []
        async def handler(request):
            calls.append(request)
            return httpx.Response(503) if len(calls) == 1 else httpx.Response(200, json={'studies': []})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await ClinicalTrialsGovAdapter(client=client, min_interval=0, max_attempts=2).search(SourceQuery('test'))
            assert result.items == [] and len(calls) == 2
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b'x' * (8 * 1024 * 1024 + 1)))) as client:
            with pytest.raises(SourceError) as info:
                await ClinicalTrialsGovAdapter(client=client, min_interval=0).search(SourceQuery('test'))
            assert info.value.code == 'SOURCE_PAYLOAD_TOO_LARGE'
    asyncio.run(run())


def test_snapshot_duplicate_rollback_failure_sequence_and_evidence():
    adapter, state = ClinicalTrialsGovAdapter(), empty_state()
    ingestor = SnapshotIngestor(state)
    a, b = adapter._envelope(trial(10)), adapter._envelope(trial(20))
    first = ingestor.ingest('ws', a, operation_key='a')
    duplicate = ingestor.ingest('ws', a, operation_key='b')
    changed = ingestor.ingest('ws', b, operation_key='c')
    failure = ingestor.record_failure('ws', source='ctgov', external_id=a.external_id, operation_key='d', error=SourceError('timeout', 'test'))
    assert ingestor.record_failure('ws', source='ctgov', external_id=a.external_id, operation_key='d', error=SourceError('timeout', 'test')) == failure
    rollback = ingestor.ingest('ws', a, operation_key='e')
    assert [o['observation_seq'] for o in state.observations.values()] == [1, 2, 3, 4, 5]
    assert duplicate['outcome'] == 'unchanged' and rollback['outcome'] == 'changed'
    assert rollback['snapshot_id'] == first['snapshot_id'] and len(state.snapshots) == 2
    assert len(state.evidence) == 2
    revisions = sorted(state.revisions.values(), key=lambda r: r['revision_no'])
    assert revisions[-1]['before_observation_id'] == changed['id']
    assert revisions[-1]['evidence_ids'] and revisions[0]['changes'][0]['path'] == '/enrollment/count'
    assert ingestor.ingest('ws', a, operation_key='e') == rollback
    # Identical source ID in another workspace never reuses another tenant's snapshot.
    other = ingestor.ingest('other', a, operation_key='a')
    assert other['snapshot_id'] != first['snapshot_id']


def test_raw_payload_change_has_new_snapshot_even_when_projection_unchanged():
    adapter, state = ClinicalTrialsGovAdapter(), empty_state()
    a, b = adapter._envelope(trial(extra='a')), adapter._envelope(trial(extra='b'))
    assert a.normalized == b.normalized and a.content_hash != b.content_hash
    ingestor = SnapshotIngestor(state)
    ingestor.ingest('ws', a, operation_key='a')
    ingestor.ingest('ws', b, operation_key='b')
    assert len(state.snapshots) == 2 and not state.events


def test_compressed_upstream_response_is_decoded_once():
    import gzip
    async def run():
        body = gzip.compress(json.dumps({'studies': [trial()]}).encode())
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body, headers={'Content-Encoding': 'gzip'}))) as client:
            page = await ClinicalTrialsGovAdapter(client=client, min_interval=0).search(SourceQuery('test'))
        assert len(page.items) == 1
    asyncio.run(run())
