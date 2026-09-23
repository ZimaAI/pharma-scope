"""Opt-in integration against real PostgreSQL, isolated in a disposable schema.

PHARMA_TEST_DATABASE_URL must name a test-only database. These tests create/drop
only a unique schema, never the public schema or existing application records.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid

import httpx
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.environ.get("PHARMA_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="PHARMA_TEST_DATABASE_URL required for real PostgreSQL integration")


def command(env, *args):
    result = subprocess.run([sys.executable, *args], cwd=ROOT, env=env, text=True, capture_output=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


@pytest.fixture
def postgres_env():
    assert TEST_DATABASE_URL and make_url(TEST_DATABASE_URL).drivername.startswith("postgres")
    schema = "pharmascope_it_" + uuid.uuid4().hex
    admin = create_engine(TEST_DATABASE_URL)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    url = make_url(TEST_DATABASE_URL).update_query_dict({"options": "-csearch_path=" + schema}).render_as_string(hide_password=False)
    env = dict(os.environ, PHARMA_DATABASE_URL=url, DATABASE_URL=url, PHARMA_RUNTIME_MODE="live", PHARMA_ALLOW_DEV_HEADER="0", PHARMA_COOKIE_SECURE="0", PHARMA_ADMIN_PASSWORD="integration-only-password-" + uuid.uuid4().hex, PH_REAL_EMAIL_ENABLED="false", PH_SMTP_DRY_RUN="true")
    for key in ("OPENAI_API_KEY", "OPENAI_API_TOKEN", "OPENAI_MODEL", "PHARMA_MODEL", "SMART_LLM", "SMART_LLM_MODEL"):
        env.pop(key, None)
    try:
        command(env, "-m", "alembic", "upgrade", "head")
        yield env
    finally:
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def bootstrap(env):
    command(env, "-m", "backend.cli", "init", "--email", "integration@pharmascope.invalid", "--workspace-name", "PostgreSQL integration")


@contextmanager
def api_process(env, tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    output = (tmp_path / ("api-" + uuid.uuid4().hex + ".log")).open("w+")
    process = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.pharma_scope_app:app", "--host", "127.0.0.1", "--port", str(port)], cwd=ROOT, env=env, stdout=output, stderr=output)
    origin = f"http://127.0.0.1:{port}"
    try:
        for _ in range(120):
            if process.poll() is not None:
                output.seek(0)
                raise AssertionError(output.read())
            try:
                if httpx.get(origin + "/healthz", timeout=.5, trust_env=False).status_code == 200:
                    break
            except httpx.TransportError:
                pass
            time.sleep(.1)
        else:
            output.seek(0)
            raise AssertionError("API did not become healthy: " + output.read())
        yield origin
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        output.close()


def login(client, env):
    result = client.post("/api/v1/auth/login", json={"email": "integration@pharmascope.invalid", "password": env["PHARMA_ADMIN_PASSWORD"]})
    assert result.status_code == 200, result.text
    payload = result.json()
    client.headers["X-CSRF-Token"] = payload["csrf_token"]
    return payload["memberships"][0]["workspace_id"]


def test_postgres_migration_repeat_and_round_trip(postgres_env):
    command(postgres_env, "-m", "alembic", "upgrade", "head")
    engine = create_engine(postgres_env["PHARMA_DATABASE_URL"])
    inspector = inspect(engine)
    assert "pharma_workspaces" in inspector.get_table_names()
    assert inspector.get_foreign_keys("pharma_observations")
    assert inspector.get_unique_constraints("pharma_records")
    assert inspector.get_indexes("pharma_runs")
    engine.dispose()
    command(postgres_env, "-m", "alembic", "downgrade", "base")
    command(postgres_env, "-m", "alembic", "upgrade", "head")


def test_postgres_live_bootstrap_does_not_seed_demo(postgres_env, tmp_path):
    bootstrap(postgres_env)
    with api_process(postgres_env, tmp_path) as origin, httpx.Client(base_url=origin, trust_env=False) as client:
        workspace = login(client, postgres_env)
        response = client.get(f"/api/v1/workspaces/{workspace}/drugs")
        assert response.status_code == 200
        assert response.json()["items"] == []
        assert client.get("/healthz").json()["mode"] == "live"
        assert client.get("/api/v1/auth/me").json()["user"]["email"] == "integration@pharmascope.invalid"
    result = command(postgres_env, "-c", "import json; from backend.gptr_adapter import PharmaResearchConductor; print(json.dumps(PharmaResearchConductor.validate_configuration()))")
    assert json.loads(result)["error_code"] == "model_credentials_missing"


def test_postgres_api_restart_preserves_record_session_and_audit(postgres_env, tmp_path):
    bootstrap(postgres_env)
    with api_process(postgres_env, tmp_path) as origin, httpx.Client(base_url=origin, trust_env=False) as client:
        workspace = login(client, postgres_env)
        response = client.post(f"/api/v1/workspaces/{workspace}/drugs", json={"display_name": "Restart persistence integration test"})
        assert response.status_code == 201, response.text
        record_id = response.json()["id"]
        cookies = dict(client.cookies)
        csrf = client.headers["X-CSRF-Token"]
    with api_process(postgres_env, tmp_path) as origin, httpx.Client(base_url=origin, cookies=cookies, headers={"X-CSRF-Token": csrf}, trust_env=False) as client:
        assert client.get("/api/v1/auth/me").status_code == 200
        response = client.get(f"/api/v1/workspaces/{workspace}/drugs/{record_id}")
        assert response.status_code == 200
        assert response.json()["display_name"] == "Restart persistence integration test"
    engine = create_engine(postgres_env["PHARMA_DATABASE_URL"])
    with engine.connect() as conn:
        audits = conn.execute(text("SELECT payload FROM pharma_audit WHERE workspace_id=:ws"), {"ws": workspace}).scalars().all()
        assert any(row["action"] == "post:drugs" for row in audits)
    engine.dispose()


def test_postgres_guest_selection_persists_and_cli_switch_revokes_session(postgres_env, tmp_path):
    bootstrap(postgres_env)
    with api_process(postgres_env, tmp_path) as origin:
        with httpx.Client(base_url=origin, trust_env=False) as admin, httpx.Client(base_url=origin, trust_env=False) as guest:
            workspace = login(admin, postgres_env)
            created = admin.post(f"/api/v1/workspaces/{workspace}/members", json={
                "email": "demo-member@pharmascope.invalid", "display_name": "Demo member",
                "password": "integration-demo-member-123", "role": "analyst",
            })
            assert created.status_code == 201, created.text
            member_id = created.json()["user"]["id"]
            drug = admin.post(f"/api/v1/workspaces/{workspace}/drugs", json={"display_name": "Guest integration data"})
            assert drug.status_code == 201, drug.text
            selected = admin.patch(f"/api/v1/workspaces/{workspace}/settings/demo-account", json={"user_id": member_id})
            assert selected.status_code == 200 and selected.json()["user_id"] == member_id

            signed_in = guest.post("/api/v1/auth/guest-login")
            assert signed_in.status_code == 200, signed_in.text
            assert signed_in.json()["is_guest"] is True
            assert signed_in.json()["memberships"] == [{
                "workspace_id": workspace, "workspace_name": "PostgreSQL integration", "role": "reader",
            }]
            assert drug.json()["id"] in {
                row["id"] for row in guest.get(f"/api/v1/workspaces/{workspace}/drugs").json()["items"]
            }
            denied = guest.post(f"/api/v1/workspaces/{workspace}/drugs", headers={
                "X-CSRF-Token": signed_in.json()["csrf_token"]
            }, json={"display_name": "Guest must not create"})
            assert denied.status_code == 403
            cookies = dict(guest.cookies)

    # A separate CLI process updates the same database while the old guest
    # session is persisted. The next API process must reject that session.
    command(postgres_env, "-m", "backend.cli", "set-demo", "--workspace-id", workspace,
            "--email", "integration@pharmascope.invalid")
    with api_process(postgres_env, tmp_path) as origin, httpx.Client(
        base_url=origin, cookies=cookies, trust_env=False
    ) as old_guest:
        assert old_guest.get("/api/v1/auth/me").status_code == 401
        fresh = old_guest.post("/api/v1/auth/guest-login")
        assert fresh.status_code == 200 and fresh.json()["is_guest"] is True
        assert old_guest.get(f"/api/v1/workspaces/{workspace}/drugs").status_code == 200


def test_postgres_two_api_processes_keep_concurrent_updates(postgres_env, tmp_path):
    bootstrap(postgres_env)
    with api_process(postgres_env, tmp_path) as first, api_process(postgres_env, tmp_path) as second:
        with httpx.Client(base_url=first, trust_env=False) as client:
            workspace = login(client, postgres_env)
            cookies, headers = dict(client.cookies), {"X-CSRF-Token": client.headers["X-CSRF-Token"]}
        def create(index):
            origin = first if index % 2 else second
            response = httpx.post(origin + f"/api/v1/workspaces/{workspace}/drugs", json={"display_name": f"Concurrent record {index}"}, cookies=cookies, headers=headers, timeout=30, trust_env=False)
            assert response.status_code == 201, response.text
            return response.json()["id"]
        with ThreadPoolExecutor(max_workers=6) as executor:
            created = list(executor.map(create, range(18)))
        for origin in (first, second):
            response = httpx.get(origin + f"/api/v1/workspaces/{workspace}/drugs?limit=100", cookies=cookies, timeout=10, trust_env=False)
            assert response.status_code == 200, response.text
            assert {row["id"] for row in response.json()["items"]} == set(created)


def test_postgres_rejects_runtime_mode_switch(postgres_env):
    bootstrap(postgres_env)
    replay = dict(postgres_env, PHARMA_RUNTIME_MODE="replay")
    result = subprocess.run([sys.executable, "-c", "from backend.repository import repository_from_env; repository_from_env()"], cwd=ROOT, env=replay, capture_output=True, text=True, timeout=20)
    assert result.returncode != 0
    assert "runtime mode differs" in result.stderr


def test_postgres_worker_claim_failure_sse_cancel_and_restart(postgres_env, tmp_path):
    bootstrap(postgres_env)
    worker_env = dict(postgres_env, PHARMA_WORKER_POLL_SECONDS="0.2")
    log = (tmp_path / "worker.log").open("w+")
    worker = subprocess.Popen([sys.executable, "-m", "backend.worker"], cwd=ROOT, env=worker_env, stdout=log, stderr=log)
    try:
        for _ in range(80):
            check = subprocess.run([sys.executable, "-m", "backend.worker", "--healthcheck"], cwd=ROOT, env=worker_env, capture_output=True, timeout=15)
            if check.returncode == 0:
                break
            time.sleep(.1)
        else:
            log.seek(0)
            raise AssertionError("Worker heartbeat missing: " + log.read())
        with api_process(postgres_env, tmp_path) as origin, httpx.Client(base_url=origin, trust_env=False, timeout=15) as client:
            workspace = login(client, postgres_env)
            result = client.post(f"/api/v1/workspaces/{workspace}/drugs", json={"display_name": "Worker integration scope"})
            assert result.status_code == 201, result.text
            drug_id = result.json()["id"]
            payload = {"question": "Summarize available scoped trial evidence and missing information.", "drug_ids": [drug_id], "source_allowlist": ["ctgov"], "time_range": {"start": "2026-01-01T00:00:00Z", "end_exclusive": "2027-01-01T00:00:00Z", "timezone": "UTC"}, "budget": {"max_model_calls": 1, "max_tool_calls": 1, "max_records": 1, "timeout_seconds": 5}}
            runs = f"/api/v1/workspaces/{workspace}/research/runs"
            result = client.post(runs, json=payload, headers={"Idempotency-Key": "worker-failure"})
            assert result.status_code == 202, result.text
            run_id = result.json()["id"]
            repeat = client.post(runs, json=payload, headers={"Idempotency-Key": "worker-failure"})
            assert repeat.status_code in (200, 202) and repeat.json()["id"] == run_id
            for _ in range(100):
                failure = client.get(runs + "/" + run_id).json()
                if failure["status"] == "failed":
                    break
                time.sleep(.1)
            else:
                log.seek(0)
                raise AssertionError("Worker did not finish queued run: " + log.read())
            assert failure["error_code"] == "MODEL_CONFIGURATION_ERROR", failure
            assert failure["report_id"] is None
            with client.stream("GET", runs + "/" + run_id + "/events", headers={"Last-Event-ID": "1"}) as stream:
                assert stream.status_code == 200
                events = list(stream.iter_lines())
                assert "id: 1" not in events
                assert any("run.failed" in line for line in events)
            # Stop only this test worker, then queue/cancel before it can claim.
            worker.terminate()
            worker.wait(timeout=10)
            cancelled = client.post(runs, json=payload, headers={"Idempotency-Key": "worker-cancel"}).json()["id"]
            response = client.post(runs + "/" + cancelled + "/cancel")
            assert response.status_code == 200 and response.json()["status"] == "cancelled"
            cookies = dict(client.cookies)
        with api_process(postgres_env, tmp_path) as origin, httpx.Client(base_url=origin, cookies=cookies, trust_env=False) as client:
            assert client.get(runs + "/" + run_id).json()["error_code"] == "MODEL_CONFIGURATION_ERROR"
            assert client.get(runs + "/" + cancelled).json()["status"] == "cancelled"
    finally:
        if worker.poll() is None:
            worker.terminate()
            try:
                worker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=5)
        log.close()
