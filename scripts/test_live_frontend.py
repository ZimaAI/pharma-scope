#!/usr/bin/env python3
"""Production browser against LIVE PostgreSQL/API/worker and real CT.gov.

Requires PHARMA_TEST_DATABASE_URL. Creates only a disposable schema and processes.
No fixtures, successful HTTP mocks, source replacements or model results. Missing
NCBI identity/model credentials intentionally produce explicit failure evidence.
"""
from __future__ import annotations
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EXPORT = ROOT / "frontend/nextjs/out"


def serve(port: int) -> None:
    assert os.environ["PHARMA_RUNTIME_MODE"] == "live"
    import uvicorn
    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    from backend.pharma_scope_app import app

    @app.get("/{asset:path}", include_in_schema=False)
    async def asset_file(asset: str):
        relative = asset.strip("/") or "index.html"
        for candidate in (EXPORT / relative, EXPORT / f"{relative}.html", EXPORT / relative / "index.html"):
            resolved = candidate.resolve()
            if resolved.is_relative_to(EXPORT) and resolved.is_file():
                return FileResponse(resolved)
        raise HTTPException(404, "Static page not found")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def stop(process):
    if process and process.poll() is None:
        process.terminate()
        try: process.wait(timeout=10)
        except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)


@contextmanager
def live_server(env, directory):
    import httpx
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    with (directory / "api.log").open("w+") as log:
        api = subprocess.Popen([sys.executable, __file__, "--serve", str(port)], cwd=ROOT, env=env, stdout=log, stderr=log)
        try:
            for _ in range(120):
                if api.poll() is not None:
                    log.seek(0); raise AssertionError("Live API failed to start: " + log.read()[-3000:])
                try:
                    if httpx.get(origin + "/readyz", timeout=1, trust_env=False).status_code == 200: break
                except httpx.TransportError: pass
                time.sleep(.1)
            else: raise AssertionError("Live API readiness timed out")
            yield origin
        finally: stop(api)


def run() -> None:
    import httpx
    from playwright.sync_api import sync_playwright, expect
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from backend.tests.test_postgres_integration import command, login

    url = os.environ.get("PHARMA_TEST_DATABASE_URL")
    assert url, "PHARMA_TEST_DATABASE_URL must identify an isolated test database"
    assert (EXPORT / "index.html").exists(), "Build production frontend first"
    schema = "pharmascope_live_browser_" + uuid.uuid4().hex
    engine = create_engine(url)
    with engine.begin() as conn: conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    private = make_url(url).update_query_dict({"options": "-csearch_path=" + schema}).render_as_string(hide_password=False)
    env = dict(os.environ, PHARMA_DATABASE_URL=private, DATABASE_URL=private,
               PHARMA_RUNTIME_MODE="live", PHARMA_ALLOW_DEV_HEADER="0", PHARMA_COOKIE_SECURE="0",
               PHARMA_ADMIN_PASSWORD="live-browser-only-" + uuid.uuid4().hex,
               PH_REAL_EMAIL_ENABLED="false", PH_SMTP_DRY_RUN="true",
               PHARMA_SOURCE_TIMEOUT="20", PHARMA_SOURCE_RETRIES="1", PHARMA_WORKER_POLL_SECONDS="0.2")
    # Never invent a real operator identity or consume an ambient model key.
    for key in ("NCBI_EMAIL", "NCBI_API_KEY", "OPENAI_API_KEY", "OPENAI_API_TOKEN", "OPENAI_MODEL", "PHARMA_MODEL", "SMART_LLM", "SMART_LLM_MODEL"):
        env.pop(key, None)
    output_dir = ROOT / "outputs"; output_dir.mkdir(exist_ok=True)
    result = {"suite": "nextjs-live-postgres-browser", "mode": "live", "fixtures_used": False,
              "source": "real ClinicalTrials.gov API v2", "model": "missing credentials; expected explicit failure", "checks": [], "success": False}
    worker = None
    def passed(name):
        result["checks"].append(name); print("PASS " + name, flush=True)
    try:
        command(env, "-m", "alembic", "upgrade", "head")
        command(env, "-m", "backend.cli", "init", "--email", "integration@pharmascope.invalid", "--workspace-name", "Live browser validation")
        with tempfile.TemporaryDirectory(prefix="pharmascope-live-browser-") as directory:
            directory = Path(directory)
            with live_server(env, directory) as origin, httpx.Client(base_url=origin, trust_env=False, timeout=30) as client, (directory / "worker.log").open("w+") as worker_log:
                ws = login(client, env); path = f"/api/v1/workspaces/{ws}"
                assert client.get(path + "/drugs").json()["items"] == []
                assert client.get(path + "/trials").json()["items"] == []
                assert client.get(path + "/reports").json()["items"] == []
                passed("live CLI bootstrap starts with zero fixture business records")
                drug = client.post(path + "/drugs", json={"display_name": "pembrolizumab", "development_code": "pembrolizumab"})
                drug.raise_for_status(); drug_id = drug.json()["id"]
                response = client.post(path + "/source-syncs", headers={"Idempotency-Key": "live-browser-source"}, json={"sources": ["ctgov", "pubmed"], "drug_ids": [drug_id], "mode": "discovery", "limit": 1})
                response.raise_for_status(); job_id = response.json()["id"]
                worker = subprocess.Popen([sys.executable, "-m", "backend.worker"], cwd=ROOT, env=env, stdout=worker_log, stderr=worker_log)
                for _ in range(120):
                    job = client.get(path + "/jobs/" + job_id).json()
                    if job.get("state") in ("completed", "partial", "failed"): break
                    time.sleep(.5)
                else: raise AssertionError("Live source sync did not finish within 60 seconds")
                result["source_job"] = job
                trials = client.get(path + "/trials").json()["items"]
                assert trials, "Real CT.gov returned no stored trial; source job: " + json.dumps(job)
                assert all(not trial.get("is_demo") and trial["external_id"].startswith("NCT") for trial in trials)
                trial = trials[0]; result["trial_ids"] = [row["external_id"] for row in trials]
                assert job["state"] == "partial", job
                pubmed = next(row for row in job["coverage"] if row["source"] == "pubmed")
                assert pubmed["status"] == "failed" and pubmed["limitations"], pubmed
                snapshot = client.get(path + f"/records/{trial['id']}/snapshots").json()["items"][0]
                assert len(snapshot["content_hash"]) == 64
                assert not snapshot.get("is_demo")
                result["snapshot"] = {key: snapshot.get(key) for key in ("content_hash", "source_updated", "first_observed_at")}
                passed("real CT.gov ingested with hash and PubMed missing-identity failure is partial")
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
                    context = browser.new_context(viewport={"width": 1440, "height": 900})
                    page = context.new_page(); errors = []; page.on("pageerror", lambda failure: errors.append(str(failure)))
                    page.goto(origin + "/login")
                    expect(page.locator(".ps-kicker")).to_contain_text("LIVE")
                    page.get_by_label("邮箱", exact=True).fill("integration@pharmascope.invalid")
                    page.get_by_label("密码", exact=True).fill(env["PHARMA_ADMIN_PASSWORD"])
                    page.get_by_role("button", name="登录", exact=True).click(); page.wait_for_url(origin + "/")
                    expect(page.locator(".ps-mode-banner")).to_contain_text("当前为 LIVE 模式")
                    expect(page.locator(".ps-breadcrumb")).to_contain_text("Live browser validation")
                    assert "REPLAY / DEMO" not in page.locator("body").inner_text()
                    passed("production browser authenticates against live PostgreSQL API and displays LIVE")
                    page.goto(origin + "/drugs")
                    expect(page.get_by_role("link", name="pembrolizumab", exact=True)).to_be_visible()
                    page.goto(origin + "/trials")
                    expect(page.get_by_role("link", name=trial["external_id"], exact=True)).to_be_visible()
                    real_title = trial["current_projection"]["title"]
                    expect(page.locator("main")).to_contain_text(real_title)
                    page.get_by_role("link", name=trial["external_id"], exact=True).click()
                    expect(page.locator("main")).to_contain_text(real_title)
                    page.get_by_text("观察记录与原始快照", exact=True).click()
                    page.get_by_role("button", name="查看快照", exact=True).first.click()
                    expect(page.locator(".ps-json")).to_contain_text(snapshot["content_hash"])
                    page.screenshot(path=str(output_dir / "live-browser-trial.png"), full_page=True)
                    passed("live trial projection, real NCT identity, observation, raw snapshot and hash render")
                    page.goto(origin + "/settings?job_id=" + job_id)
                    expect(page.get_by_role("status")).to_contain_text("partial")
                    expect(page.get_by_role("status")).to_contain_text("failed")
                    expect(page.get_by_role("status")).to_contain_text("pubmed")
                    expect(page.get_by_role("status")).to_contain_text("NCBI_EMAIL")
                    page.screenshot(path=str(output_dir / "live-browser-source-partial.png"), full_page=True)
                    passed("persisted partial source job distinguishes missing NCBI_EMAIL from no results")
                    links = client.get(path + "/entity-links?status=pending").json()["items"]
                    assert len(links) == 1, links
                    page.goto(origin + "/workspace")
                    expect(page.locator("main")).to_contain_text(trial["id"])
                    page.get_by_label("关联审核备注", exact=True).fill("Checked real ClinicalTrials.gov intervention identity for pembrolizumab.")
                    page.get_by_role("button", name="确认关联", exact=True).click()
                    expect(page.locator(".ps-status")).to_contain_text("approved")
                    assert client.get(path + "/entity-links?status=approved").json()["items"][0]["id"] == links[0]["id"]
                    passed("browser approves real pending drug-record association through RBAC/CSRF API")
                    page.goto(origin + "/research/new?drug_id=" + drug_id)
                    page.get_by_label("你想了解什么？").fill("Summarize the available ClinicalTrials.gov registry evidence for pembrolizumab.")
                    page.get_by_label("时间窗口", exact=True).select_option("365")
                    page.get_by_label("PubMed", exact=True).uncheck()
                    page.get_by_role("button", name="开始研究 →").click()
                    page.wait_for_url("**/research/detail?id=*")
                    expect(page.locator("main")).to_contain_text("MODEL_CONFIGURATION_ERROR", timeout=30000)
                    expect(page.locator(".ps-status")).to_contain_text("failed")
                    expect(page.locator("main")).to_contain_text("OPENAI_API_KEY")
                    run_id = page.url.split("id=", 1)[1]
                    run_result = client.get(path + "/research/runs/" + run_id).json()
                    assert run_result["runtime_mode"] == "live" and run_result["status"] == "failed"
                    assert run_result["report_id"] is None and run_result["usage"]["model_calls"] == 0
                    assert client.get(path + "/reports").json()["items"] == []
                    result["research_failure"] = {key: run_result.get(key) for key in ("status", "error_code", "error_message", "runtime_mode", "report_id", "usage")}
                    page.screenshot(path=str(output_dir / "live-browser-model-configuration.png"), full_page=True)
                    passed("live worker/model configuration failure is visible with no fabricated report or model result")
                    assert not errors, errors
                    passed("live production browser has no JavaScript runtime errors")
                    browser.close()
                stop(worker); worker = None
        result["success"] = True
    finally:
        stop(worker)
        with engine.begin() as conn: conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()
        result["cleanup"] = "test API/worker stopped; disposable PostgreSQL schema dropped"
        (output_dir / "live-frontend-results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--serve": serve(int(sys.argv[2]))
    else: run()
