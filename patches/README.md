# PharmaScope pinned GPT Researcher extension

Base: GPT Researcher 0.14.7, commit `8da8d8f85d7124649bb059ce1b2106ed3d3f5ea5` (MIT).

`gpt_researcher/agent.py` adds optional `lite_profile`, `research_conductor_factory`,
and `report_generator_factory` constructor arguments. In this explicit profile
only, factories are installed before retrievers, Memory, browser, MCP or image
services are initialized. Existing callers keep the upstream path unchanged.
`conduct_research()` and `write_report()` remain the upstream lifecycle entrypoints;
the domain conductor and structured writer live in `backend/research.py`.

The conductor owns one model-selected tool loop with two read-only tools over
server-authorized persisted snapshots. Every request is made through an instance
OpenAI-compatible client with SDK retries disabled. Call, tool, record, token and
wall-clock budgets are checked before side effects; unknown token usage is
reserved conservatively and reported as unknown. No monkeypatch or process-global
model configuration is used. A complete tool round emits a recovery checkpoint;
a crashed in-flight model request may be replayed and is never called exactly-once.

Upgrade conflicts: constructor initialization and lifecycle delegation in agent.py;
OpenAI chat-completion response/tool contracts; report JSON schema. Run
`pytest backend/tests/test_research_runtime.py` plus the real import probe after
an upgrade. Offline contract tests use an explicitly injected model test client;
only a separately recorded credentialed run can establish live model availability.

`gpt_researcher/config/config.py` also accepts `lite_profile=True` and skips
retriever discovery, whose upstream eager discovery otherwise imports unused
arXiv/search provider extras even when no retriever is invoked. The regular
configuration path is unchanged. The runtime dependency lock is
`backend/requirements-runtime.lock`; its 79-package closure was installed into
an independent CPython 3.12 virtual environment and passed import, `pip check`,
and the source/research contract suites on 2026-09-23. These are adapter checks,
not evidence of a credentialed external model execution.
