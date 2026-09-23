"""Configuration/import probe and compatibility entrypoint for the pinned GPTR fork."""
from __future__ import annotations

import importlib
import inspect
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .research import (ResearchBudget, ResearchContext, ResearchConfigurationError,
                       PharmaResearchConductor as DomainConductor, live_model_configuration)

UPSTREAM_VERSION = "0.14.7"
UPSTREAM_COMMIT = "8da8d8f85d7124649bb059ce1b2106ed3d3f5ea5"


class GPTResearcherError(RuntimeError):
    def __init__(self, code: str, message: str, *, cause: Exception | None = None):
        super().__init__(message)
        self.code, self.cause = code, cause


@dataclass
class ResearchResult:
    report: Any
    context: Any
    sources: list[Any] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    elapsed_seconds: float = 0.0


class PharmaResearchConductor:
    def __init__(self, *, event_sink: Callable | None = None, **_: Any):
        self.event_sink = event_sink

    @staticmethod
    def validate_configuration() -> dict[str, Any]:
        mode = os.getenv("PHARMA_RUNTIME_MODE", os.getenv("PHARMA_MODE", "live"))
        if mode not in {"live", "gptr"}:
            return {"configured": False, "mode": mode, "reason": "replay_mode"}
        try:
            config = live_model_configuration()
            return {"configured": True, "mode": mode, "model": config["model"], "base_url": config["base_url"]}
        except ResearchConfigurationError as exc:
            return {"configured": False, "mode": mode, "error_code": "model_credentials_missing" if "API_KEY" in str(exc) else "model_configuration_missing", "message": str(exc)}

    @classmethod
    def probe(cls) -> dict[str, Any]:
        config = cls.validate_configuration()
        try:
            module = importlib.import_module("gpt_researcher")
            factory = module.GPTResearcher
            patched = "lite_profile" in inspect.signature(factory).parameters
            config.update(imported=True, upstream_version=UPSTREAM_VERSION, upstream_commit=UPSTREAM_COMMIT, lite_profile=patched)
            if not patched:
                config.update(configured=False, error_code="gptr_patch_missing", message="Install the pinned PharmaScope fork with its Lite profile injection patch")
        except Exception as exc:
            config.update(imported=False, error_code="gptr_import_failed", message=f"GPT Researcher import failed ({type(exc).__name__})")
        return config

    async def run(self, *, question: str, source_allowlist: list[str], time_range: dict[str, Any], drug_ids: list[str], budget: ResearchBudget | dict[str, Any] | None = None, cancel_event=None, evidence: list[dict[str, Any]] | None = None, workspace_id: str = "", run_id: str = "") -> ResearchResult:
        if evidence is None or not workspace_id or not run_id:
            raise GPTResearcherError("authorized_context_required", "Live research requires server-authorized workspace/run context and persisted evidence; open-web fallback is disabled")
        started = time.monotonic()
        context = ResearchContext(workspace_id, run_id, question, source_allowlist, drug_ids, time_range,
                                  budget if isinstance(budget, ResearchBudget) else ResearchBudget.from_mapping(budget),
                                  evidence=evidence, emit=self.event_sink, cancel_event=cancel_event)
        try:
            result = await DomainConductor(context).run()
        except Exception as exc:
            raise GPTResearcherError(getattr(exc, "code", "gptr_execution_failed"), str(exc), cause=exc) from exc
        return ResearchResult(result["report"], result["evidence"], result["evidence"], result["usage"], time.monotonic() - started)
