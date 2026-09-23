import asyncio
from pathlib import Path

from backend.repository import PersistentStateStore, restore_state, state_payload
from backend.gptr_adapter import GPTResearcherError, PharmaResearchConductor, ResearchBudget


def test_sqlite_checkpoint_survives_new_store(tmp_path: Path):
    url = f"sqlite:///{tmp_path / 'state.db'}"
    class S:
        users = {"u": {"id": "u", "email":"u@example.invalid"}}
        workspaces = {"w":{"id":"w","name":"Test"}}
        memberships = {("w", "u"): {"workspace_id":"w","user_id":"u","role": "admin"}}
        sessions = {}
    first = PersistentStateStore(url); first.save(state_payload(S()))
    payload = PersistentStateStore(url).load()
    restored = S(); restore_state(restored, payload)
    assert restored.users == S.users and restored.memberships[("w", "u")]["role"] == "admin"


def test_gptr_missing_credentials_is_explicit(monkeypatch):
    monkeypatch.setenv("PHARMA_RUNTIME_MODE", "live")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    result = PharmaResearchConductor.validate_configuration()
    assert not result["configured"] and result["error_code"] == "model_credentials_missing"
