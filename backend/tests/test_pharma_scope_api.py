"""Contract smoke tests for the replay backend.

The suite deliberately exercises authorization and immutable evidence paths in
addition to happy-path listing.  It runs with ``pytest`` after installing
``backend/requirements.txt``.
"""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.pharma_scope_app import app, DEFAULT_WORKSPACE, DEFAULT_USER, REVIEWER_USER


def login(client: TestClient, email: str):
    result = client.post("/api/v1/auth/login", json={"email": email, "password": "demo"})
    assert result.status_code == 200, result.text
    body = result.json()
    return body["csrf_token"]


def test_health_and_demo_login():
    with TestClient(app) as client:
        health = client.get("/healthz")
        assert health.status_code == 200 and health.headers.get("x-request-id")
        csrf = login(client, "analyst@pharmascope.invalid")
        me = client.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["user"]["id"] == DEFAULT_USER
        assert csrf


def test_drug_trial_snapshot_and_diff_flow():
    with TestClient(app) as client:
        login(client, "analyst@pharmascope.invalid")
        drugs = client.get(f"/api/v1/workspaces/{DEFAULT_WORKSPACE}/drugs")
        assert drugs.status_code == 200 and len(drugs.json()["items"]) >= 2
        trials = client.get(f"/api/v1/workspaces/{DEFAULT_WORKSPACE}/trials")
        assert trials.status_code == 200 and trials.json()["items"]
        record = trials.json()["items"][0]["id"]
        observations = client.get(f"/api/v1/workspaces/{DEFAULT_WORKSPACE}/records/{record}/observations").json()["items"]
        assert len(observations) >= 2
        diff = client.get(f"/api/v1/workspaces/{DEFAULT_WORKSPACE}/records/{record}/diff", params={"before_observation_id": observations[1]["id"], "after_observation_id": observations[2]["id"]})
        assert diff.status_code == 200
        assert any(c["path"] in ("/status", "/enrollment") for c in diff.json()["changes"])


def test_csrf_role_and_cross_workspace_isolation():
    with TestClient(app) as client:
        csrf = login(client, "analyst@pharmascope.invalid")
        # Mutations require a CSRF token.
        denied = client.post(f"/api/v1/workspaces/{DEFAULT_WORKSPACE}/drugs", json={"display_name": "PX-test"})
        assert denied.status_code == 403
        created = client.post(f"/api/v1/workspaces/{DEFAULT_WORKSPACE}/drugs", headers={"X-CSRF-Token": csrf}, json={"display_name": "PX-test"})
        assert created.status_code == 201
        # The analyst cannot access an isolated workspace.
        hidden = client.get("/api/v1/workspaces/b9c9d1b4-62c5-5b58-92d1-de56235db31d/drugs")
        assert hidden.status_code == 404
        # Reviewer cannot review their own report version (self review guard).
        login(client, "reviewer@pharmascope.invalid")
        reports = client.get(f"/api/v1/workspaces/{DEFAULT_WORKSPACE}/reports").json()["items"]
        assert reports


def test_research_run_and_sse_contract():
    with TestClient(app) as client:
        csrf = login(client, "analyst@pharmascope.invalid")
        payload = {"question": "整理PX-101最近试验变化并列明证据", "drug_ids": ["dd1dcb81-e4b6-5343-b4a6-544bf716d867"], "time_range": {"start": "2026-09-14T00:00:00Z", "end_exclusive": "2026-09-18T00:00:00Z", "timezone": "Asia/Shanghai"}, "source_allowlist": ["ctgov", "pubmed"]}
        created = client.post(f"/api/v1/workspaces/{DEFAULT_WORKSPACE}/research/runs", headers={"X-CSRF-Token": csrf}, json=payload)
        assert created.status_code == 202, created.text
        run = created.json()
        assert run["runtime_mode"] in ("replay", "gptr") and run["event_seq"] >= 1 and run["report_id"]
        stream = client.get(f"/api/v1/workspaces/{DEFAULT_WORKSPACE}/research/runs/{run['id']}/events", headers={"Accept": "text/event-stream"})
        assert stream.status_code == 200 and "run.completed" in stream.text
