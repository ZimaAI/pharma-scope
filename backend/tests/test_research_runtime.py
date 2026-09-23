"""Offline adapter contracts: real GPTR lifecycle + explicitly mocked HTTP model."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from openai import AsyncOpenAI

from backend.research import (PharmaResearchConductor, ResearchBudget, ResearchBudgetExceeded,
                              ResearchContext, ResearchOutputError, live_model_configuration)

EVIDENCE_ID = "a48c008c-00cc-47cb-8cc8-2192aba94af5"
WORKSPACE_ID = "89e5b360-8ae4-4e07-9986-ac21d469208e"
DRUG_ID = "9c586f06-c134-47ea-a17e-c8a5a1698e36"


def context(**kwargs):
    return ResearchContext(workspace_id=WORKSPACE_ID, run_id="run-test", question="What trial status is reported?",
        source_allowlist=["ctgov"], drug_ids=[DRUG_ID],
        time_range={"start": "2026-09-01T00:00:00Z", "end_exclusive": "2026-10-01T00:00:00Z", "timezone": "UTC"},
        budget=kwargs.pop("budget", ResearchBudget(max_model_calls=3)),
        evidence=[{"evidence_id": EVIDENCE_ID, "workspace_id": WORKSPACE_ID, "source": "ctgov", "normalized": {"title": "Synthetic contract-test trial", "status": "RECRUITING"}}], **kwargs)


def report(evidence_id=EVIDENCE_ID):
    return {"schema_version": "1.0", "title": "Contract test output", "summary": "The authorized test snapshot reports recruiting.",
            "scope": {}, "coverage": [], "sections": [{"heading": "Observed status", "text": "Recruiting [C1].", "claim_keys": ["C1"]}],
            "claims": [{"claim_key": "C1", "statement": "The test snapshot reports recruiting.", "category": "fact",
                        "qualifiers": {"population": None, "trial_ids": [], "time_scope": None, "limitations": []},
                        "evidence_links": [{"evidence_id": evidence_id, "relation": "supports"}]}],
            "limitations": ["Offline transport contract test; not live research evidence."], "unanswered_questions": [], "event_revision_ids": []}


def response(index, *, bad_id=False):
    if index == 1:
        message = {"role": "assistant", "content": None, "tool_calls": [{"id": "s1", "type": "function", "function": {"name": "search_evidence", "arguments": '{"source":"ctgov"}'}}]}
    elif index == 2:
        message = {"role": "assistant", "content": None, "tool_calls": [{"id": "r1", "type": "function", "function": {"name": "read_evidence", "arguments": json.dumps({"evidence_ids": [EVIDENCE_ID]})}}]}
    else:
        message = {"role": "assistant", "content": json.dumps(report("92496f09-2ad9-466e-817a-9b04e5ab9475" if bad_id else EVIDENCE_ID))}
    return {"id": f"test-{index}", "object": "chat.completion", "created": 1, "model": "test-model", "choices": [{"index": 0, "message": message, "finish_reason": "stop"}], "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}}


@pytest.fixture(autouse=True)
def model_config(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "contract-test-key")
    monkeypatch.setenv("PHARMA_MODEL", "openai:test-model")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://model.invalid/v1")


def test_real_gptr_lifecycle_uses_only_authorized_tools_and_explicit_model():
    async def run():
        calls, events = [], []
        async def handler(request):
            calls.append(json.loads(request.content))
            assert request.url.path == "/v1/chat/completions"
            return httpx.Response(200, json=response(len(calls)))
        async def sink(typ, payload):
            events.append((typ, payload))
        async with AsyncOpenAI(api_key="contract-test-key", base_url="https://model.invalid/v1", max_retries=0, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))) as client:
            result = await PharmaResearchConductor(context(emit=sink), model_client=client).run()
        assert len(calls) == 3 and all(c["model"] == "test-model" for c in calls)
        assert result["usage"]["model_calls"] == 3 and result["usage"]["tool_calls"] == 2
        assert result["usage"]["total_tokens"] == 60
        assert result["report"]["claims"][0]["evidence_links"][0]["evidence_id"] == EVIDENCE_ID
        assert result["coverage"][0]["status"] == "partial"
        assert any(t == "researcher.imported" and p["entrypoint"].startswith("GPTResearcher.") for t, p in events)
        assert len([t for t, _ in events if t == "research.checkpoint"]) == 2
    asyncio.run(run())


def test_tool_budget_is_checked_before_second_tool_invocation():
    async def run():
        calls = []
        async def handler(request):
            calls.append(request)
            return httpx.Response(200, json=response(len(calls)))
        async with AsyncOpenAI(api_key="x", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))) as client:
            ctx = context(budget=ResearchBudget(max_model_calls=3, max_tool_calls=1))
            with pytest.raises(ResearchBudgetExceeded, match="Tool call"):
                await PharmaResearchConductor(ctx, model_client=client).run()
            assert ctx.budget.tool_calls == 1 and len(calls) == 2
    asyncio.run(run())


def test_unknown_evidence_id_in_writer_is_rejected():
    async def run():
        calls = 0
        async def handler(request):
            nonlocal calls
            calls += 1
            return httpx.Response(200, json=response(calls, bad_id=True))
        async with AsyncOpenAI(api_key="x", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))) as client:
            with pytest.raises(ResearchOutputError, match="unauthorized"):
                await PharmaResearchConductor(context(), model_client=client).run()
    asyncio.run(run())


def test_cancellation_reclaims_pending_model_request():
    async def run():
        started = asyncio.Event()
        stopped = asyncio.Event()
        async def create(**kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        task = asyncio.create_task(PharmaResearchConductor(context(), model_client=client).run())
        await asyncio.wait_for(started.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stopped.is_set()
    asyncio.run(run())


def test_total_timeout_and_model_error_do_not_fabricate_report():
    async def run():
        async def create(**kwargs):
            await asyncio.sleep(1)
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with pytest.raises(ResearchBudgetExceeded, match="timeout"):
            await PharmaResearchConductor(context(budget=ResearchBudget(timeout_seconds=.02)), model_client=client).run()
    asyncio.run(run())


def test_restored_model_budget_is_not_reset():
    async def run():
        async def create(**kwargs):
            pytest.fail("exhausted budget must not issue model request")
        conductor = PharmaResearchConductor(context(budget=ResearchBudget.from_mapping({"max_model_calls": 2}, {"model_calls": 2, "tool_calls": 1})), model_client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
        with pytest.raises(ResearchBudgetExceeded, match="Model call"):
            await conductor.completion([{"role": "user", "content": "test"}])
    asyncio.run(run())


def test_checkpoint_restores_completed_evidence_reads():
    async def run():
        checkpoint = {"phase": "tool_round_completed", "messages": [{"role": "user", "content": "Resume offline contract test"}], "selected_evidence_ids": [EVIDENCE_ID]}
        budget = ResearchBudget.from_mapping({"max_model_calls": 3}, {"model_calls": 2, "tool_calls": 2, "records": 1})
        calls = []
        async def handler(request):
            calls.append(request)
            return httpx.Response(200, json=response(3))
        async with AsyncOpenAI(api_key="x", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))) as client:
            result = await PharmaResearchConductor(context(checkpoint=checkpoint, budget=budget), model_client=client).run()
        assert len(calls) == 1 and result["usage"]["model_calls"] == 3
    asyncio.run(run())


def test_tool_arguments_cannot_override_workspace():
    async def run():
        conductor = PharmaResearchConductor(context())
        with pytest.raises(ResearchOutputError, match="contract"):
            await conductor.tool("read_evidence", json.dumps({"evidence_ids": [EVIDENCE_ID], "workspace_id": "other"}))
        assert conductor.context.budget.tool_calls == 0
    asyncio.run(run())


def test_wrong_workspace_or_demo_evidence_is_rejected():
    async def run():
        ctx = context()
        ctx.evidence[0]["workspace_id"] = "other"
        with pytest.raises(ResearchOutputError, match="scope"):
            await PharmaResearchConductor(ctx).run()
    asyncio.run(run())


def test_environment_configuration_is_per_run_not_global_mutation(monkeypatch):
    monkeypatch.setenv("SMART_LLM", "openai:unrelated")
    assert live_model_configuration()["model"] == "test-model"
    import os
    assert os.environ["SMART_LLM"] == "openai:unrelated"


def test_unknown_usage_reservation_survives_restore_and_server_caps(monkeypatch):
    monkeypatch.setenv('PH_MAX_MODEL_CALLS', '3')
    budget = ResearchBudget.from_mapping({'max_model_calls': 90}, {'model_calls': 1, 'total_tokens': None, 'reserved_tokens': 4000, 'usage_quality': 'unknown'})
    assert budget.max_model_calls == 3 and budget.tokens == 4000
    assert budget.usage()['total_tokens'] is None and budget.usage()['reserved_tokens'] == 4000


def test_model_error_is_redacted_and_reserved_before_side_effect():
    async def run():
        events = []
        async def create(**kwargs):
            raise RuntimeError('sensitive-api-key must not appear in stored error')
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        ctx = context(emit=lambda typ, payload: events.append((typ, payload)))
        conductor = PharmaResearchConductor(ctx, model_client=client)
        with pytest.raises(RuntimeError, match='Model request failed') as info:
            await conductor.completion([{'role':'user','content':'test'}])
        assert 'sensitive-api-key' not in str(info.value)
        assert events[0][1]['usage']['reserved_tokens'] > 0
        assert ctx.budget.model_calls == 1 and ctx.budget.usage()['usage_quality'] == 'unknown'
    asyncio.run(run())


def test_explicit_cancel_event_interrupts_inflight_model():
    async def run():
        started,cancelled,stopped=asyncio.Event(),asyncio.Event(),asyncio.Event()
        async def create(**kwargs):
            started.set()
            try:await asyncio.Event().wait()
            finally:stopped.set()
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        task=asyncio.create_task(PharmaResearchConductor(context(cancel_event=cancelled),model_client=client).run())
        await asyncio.wait_for(started.wait(),5)
        cancelled.set()
        with pytest.raises(asyncio.CancelledError):await asyncio.wait_for(task,1)
        assert stopped.is_set()
    asyncio.run(run())


def test_tool_result_envelope_and_failed_tool_are_persistable():
    from pathlib import Path
    import jsonschema
    async def run():
        events=[]
        conductor=PharmaResearchConductor(context(emit=lambda typ,payload:events.append((typ,payload))))
        result=await conductor.tool('search_evidence','{"source":"ctgov"}')
        schema=json.loads((Path(__file__).resolve().parents[2]/'docs/reference/PharmaScope_Lite_v1.0/contracts/tool-result.schema.json').read_text())
        jsonschema.validate(result,schema)
        assert result['data']['items'][0]['evidence_id']==EVIDENCE_ID
        assert result['provenance']['cache_hit'] and result['provenance']['fetched_at'] is None
        with pytest.raises(ResearchOutputError):
            await conductor.tool('read_evidence','{"evidence_ids":["unauthorized"]}')
        assert events[-1][0]=='tool.failed' and events[-1][1]['error_code']=='INVALID_RESEARCH_OUTPUT'
    asyncio.run(run())
