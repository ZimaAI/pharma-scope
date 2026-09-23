#!/usr/bin/env python3
"""Real Chromium tests of the production Next export against a real replay API.

No prototype HTML and no mocked successful business responses. Error injection
is restricted to checking explicit 4xx/5xx UI handling. Replay fixtures are not
claimed as live model/source verification. Uses an isolated ephemeral port.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EXPORT = ROOT / "frontend/nextjs/out"
WORKSPACE = "dee59b72-2cb2-5255-934c-b44a3fd8911c"
BASE_API = f"/api/v1/workspaces/{WORKSPACE}"

def serve(port: int) -> None:
    import uvicorn
    from fastapi.responses import FileResponse
    from backend.pharma_scope_app import app, state, emit, now, DEFAULT_USER
    # Explicit replay-only queued fixture exercises real cancel/retry endpoints.
    import copy
    queued = copy.deepcopy(next(iter(state.runs.values())))
    queued.update(id="browser-queued-replay", status="queued", created_by=DEFAULT_USER, report_id=None, question="Browser queued replay cancellation", event_seq=0, next_event_seq=0, created_at=now())
    state.runs[queued["id"]] = queued
    state.run_events[queued["id"]] = []
    emit(queued["id"], "run.queued", {"runtime_mode": "replay"})

    @app.get("/{asset:path}", include_in_schema=False)
    async def static_asset(asset: str):
        from fastapi import HTTPException
        relative = asset.strip("/") or "index.html"
        for candidate in [EXPORT / relative, EXPORT / f"{relative}.html", EXPORT / relative / "index.html"]:
            resolved = candidate.resolve()
            if resolved.is_relative_to(EXPORT) and resolved.is_file():
                return FileResponse(resolved)
        raise HTTPException(404, "Static page not found")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def run() -> None:
    from playwright.sync_api import sync_playwright, expect
    assert (EXPORT / "index.html").exists(), "Run npm --prefix frontend/nextjs run build first"
    assert not any("localhost:8000" in p.read_text() for p in (EXPORT / "_next/static").rglob("*.js")), "Browser bundle contains localhost:8000"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
    env = {**os.environ, "PHARMA_RUNTIME_MODE": "replay", "PHARMA_ALLOW_DEV_HEADER": "0", "PHARMA_COOKIE_SECURE": "0", "PHARMA_DEMO_PASSWORD": "browser-e2e-only", "PHARMA_DATABASE_URL": "", "DATABASE_URL": "", "PH_REAL_EMAIL_ENABLED": "false"}
    (ROOT / "outputs").mkdir(exist_ok=True)
    result = {"suite": "nextjs-production-browser", "mode": "real replay API; no live-source/model claim", "checks": [], "success": False}
    def passed(name):
        result["checks"].append(name); print(f"PASS {name}", flush=True)
    with tempfile.TemporaryDirectory(prefix="pharmascope-e2e-") as temp:
        with open(Path(temp) / "api.log", "w+") as output:
            process = subprocess.Popen([sys.executable, __file__, "--serve", str(port)], cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT)
            origin = f"http://127.0.0.1:{port}"
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        output.seek(0); raise RuntimeError(output.read())
                    try:
                        urllib.request.urlopen(origin + "/healthz", timeout=1); break
                    except OSError: time.sleep(.1)
                else: raise RuntimeError("E2E API failed to start")
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
                    context = browser.new_context(viewport={"width": 1440, "height": 900}, service_workers="block")
                    page = context.new_page(); errors = []; page.on("pageerror", lambda error: errors.append(str(error)))
                    def login(role):
                        page.goto(origin + "/login")
                        expect(page.get_by_role("button", name="登录", exact=True)).to_be_visible()
                        expect(page.get_by_label("邮箱", exact=True)).to_have_count(0)
                        page.get_by_role("button", name="使用工作区账号").click()
                        page.get_by_label("邮箱", exact=True).fill(f"{role}@pharmascope.invalid")
                        page.get_by_label("密码", exact=True).fill("browser-e2e-only")
                        page.get_by_role("button", name="账号密码登录").click()
                        page.wait_for_url(origin + "/")
                        expect(page.locator(".ps-mode-banner")).to_contain_text("REPLAY / DEMO")
                    page.goto(origin + "/")
                    page.wait_for_url("**/login")
                    expect(page.get_by_role("button", name="登录", exact=True)).to_be_visible()
                    expect(page.get_by_role("link", name="浙ICP备2026076087号-1")).to_be_visible()
                    passed("unauthenticated domain entry opens guest-first login page with ICP footer")
                    login("analyst")
                    passed("cookie login, CSRF restoration, server runtime mode")
                    page.goto(origin + "/drugs")
                    page.get_by_role("button", name="＋ 建立药物档案").click()
                    page.get_by_label("药物名称", exact=True).fill("Browser E2E Object")
                    page.get_by_label("研发代号", exact=True).fill("E2E-ONLY")
                    page.get_by_role("button", name="保存档案").click()
                    expect(page.get_by_role("link", name="Browser E2E Object", exact=True)).to_be_visible()
                    page.reload(); expect(page.get_by_role("link", name="Browser E2E Object", exact=True)).to_be_visible()
                    passed("drug creation posts real CSRF-authenticated API and reloads")
                    no_csrf = context.request.post(origin + BASE_API + "/drugs", data={"display_name": "invalid"})
                    assert no_csrf.status == 403
                    passed("server rejects missing CSRF")
                    for path, title in [("/trials", "临床试验"), ("/literature", "研究文献"), ("/events", "变化追踪"), ("/reports", "报告中心"), ("/inbox", "通知")]:
                        page.goto(origin + path); expect(page.get_by_role("heading", name=title, exact=True)).to_be_visible(); expect(page.locator(".ps-error-state[role=alert]")).to_have_count(0)
                    pubs = context.request.get(origin + BASE_API + "/publications").json()["items"]
                    page.goto(origin + "/literature/detail/?id=" + pubs[0]["id"])
                    expect(page.locator("main")).to_contain_text(pubs[0]["current_projection"]["title"])
                    events = context.request.get(origin + BASE_API + "/events").json()["items"]
                    page.goto(origin + "/events/detail/?id=" + events[0]["id"])
                    page.get_by_role("button", name="查看证据").first.click()
                    expect(page.get_by_role("dialog")).to_contain_text("/normalized/")
                    page.keyboard.press("Escape"); expect(page.get_by_role("dialog")).to_have_count(0)
                    passed("source lists, publication projection, event revisions and evidence snapshot")
                    page.goto(origin + "/research/detail/?id=browser-queued-replay")
                    page.get_by_role("button", name="取消任务", exact=True).click()
                    expect(page.locator(".ps-status")).to_contain_text("cancelled")
                    page.get_by_role("button", name="重试运行").click()
                    expect(page.locator(".ps-status")).to_contain_text("completed")
                    passed("queued replay task cancels and retries through API")
                    sse_attempts = [0]
                    def interrupt_first_stream(route):
                        sse_attempts[0] += 1
                        route.abort() if sse_attempts[0] == 1 else route.continue_()
                    page.route("**/research/runs/*/events", interrupt_first_stream)
                    page.goto(origin + "/research/new")
                    page.get_by_label("你想了解什么？").fill("浏览器测试：整理登记变化和来源证据。")
                    page.get_by_role("button", name="开始研究 →").click()
                    page.wait_for_url("**/research/detail?id=*")
                    expect(page.locator("main")).to_contain_text("run.completed", timeout=10000)
                    assert sse_attempts[0] >= 2, "SSE failed to reconnect"
                    page.unroute("**/research/runs/*/events")
                    passed("SSE reconnects after an injected transport failure")
                    page.get_by_role("link", name="查看报告与证据 →").click()
                    expect(page.locator("main")).to_contain_text("版本哈希：")
                    expect(page.get_by_role("button", name="批准版本")).to_be_disabled()
                    page.get_by_text("创建修订版本", exact=True).click()
                    page.get_by_label("报告摘要", exact=True).fill("浏览器修订：演示登记字段变化，不支持疗效结论。")
                    page.get_by_label("修订说明", exact=True).fill("核对摘要措辞")
                    page.get_by_role("button", name="保存新版本").click()
                    expect(page.locator("article")).to_contain_text("浏览器修订：")
                    page.get_by_role("button", name="提交审核").click()
                    expect(page.locator(".ps-status")).to_contain_text("审核中")
                    report_url = page.url
                    passed("replay research API, named SSE events, full report, author cannot approve")
                    page.get_by_role("button", name="退出登录").click(); page.wait_for_url("**/login")
                    login("reviewer"); page.goto(report_url)
                    page.get_by_label("审核备注").fill("已核对版本、范围和证据。")
                    page.get_by_role("checkbox").check()
                    page.get_by_role("button", name="退回修改").click()
                    expect(page.locator(".ps-status")).to_contain_text("需修改")
                    page.get_by_role("button", name="退出登录").click(); page.wait_for_url("**/login")
                    login("analyst"); page.goto(report_url)
                    page.get_by_role("button", name="提交审核").click()
                    expect(page.locator(".ps-status")).to_contain_text("审核中")
                    page.get_by_role("button", name="退出登录").click(); page.wait_for_url("**/login")
                    login("reviewer"); page.goto(report_url)
                    page.get_by_label("审核备注").fill("复核范围和证据完成。")
                    page.get_by_role("checkbox").check()
                    page.get_by_role("button", name="批准版本").click()
                    expect(page.locator(".ps-status")).to_contain_text("已批准")
                    page.get_by_role("button", name="发布报告").click()
                    expect(page.locator(".ps-status")).to_contain_text("已发布")
                    page.screenshot(path=str(ROOT / "outputs/frontend-e2e-report.png"), full_page=True)
                    passed("independent review and publish via real API")
                    page.goto(origin + "/subscriptions")
                    page.get_by_role("button", name="＋ 新建订阅").click()
                    page.get_by_label("订阅名称", exact=True).fill("Browser weekly digest")
                    page.get_by_role("button", name="预览时间").click()
                    expect(page.get_by_role("status")).to_contain_text("下次执行时间")
                    page.get_by_role("button", name="保存订阅").click()
                    expect(page.get_by_role("heading", name="Browser weekly digest")).to_be_visible()
                    page.get_by_role("button", name="暂停", exact=True).click()
                    expect(page.locator(".ps-status")).to_contain_text("已暂停")
                    page.get_by_role("button", name="立即生成").click()
                    expect(page.get_by_role("status")).to_contain_text("已创建调度任务")
                    passed("subscription timezone preview, create, pause, trigger")
                    page.goto(origin + "/settings")
                    page.get_by_role("button", name="同步 ClinicalTrials.gov", exact=True).click()
                    expect(page.get_by_role("status")).to_contain_text("completed")
                    passed("source sync job and coverage shown from replay API")
                    page.goto(origin + "/drugs/detail/?id=does-not-exist")
                    expect(page.locator(".ps-error-state[role=alert]")).to_contain_text("请求的资源不存在")
                    passed("real missing-resource 404")
                    for code, message in [(403, "没有执行此操作的权限"), (409, "请求与当前资源状态冲突"), (422, "请求参数无效"), (503, "测试来源不可用")]:
                        pattern = "**/api/v1/workspaces/*/drugs?*"
                        page.route(pattern, lambda route, _request, code=code: route.fulfill(status=code, content_type="application/json", body=json.dumps({"error": {"code": "TEST_ERROR", "message": "测试来源不可用", "request_id": "browser-error-check"}})))
                        page.goto(origin + "/drugs"); expect(page.locator(".ps-error-state[role=alert]")).to_contain_text(message); expect(page.locator(".ps-error-state[role=alert]")).to_contain_text("browser-error-check")
                        page.unroute(pattern)
                    passed("403/409/422/503 render server error and request ID without data fallback")
                    page.get_by_role("button", name="退出登录").click(); page.wait_for_url("**/login")
                    login("admin")
                    page.goto(origin + "/settings")
                    page.get_by_role("button", name="检查 ClinicalTrials.gov", exact=True).click()
                    expect(page.get_by_role("status")).to_contain_text("completed")
                    passed("admin source health-check job")
                    page.goto(origin + "/workspace")
                    expect(page.get_by_role("heading", name="工作区成员", exact=True)).to_be_visible()
                    expect(page.get_by_label("analyst@pharmascope.invalid 角色")).to_have_value("analyst")
                    passed("workspace members load from role-protected API")
                    page.get_by_label("切换工作区").select_option("b9c9d1b4-62c5-5b58-92d1-de56235db31d")
                    expect(page.locator(".ps-breadcrumb")).to_contain_text("隔离测试组")
                    page.goto(origin + "/drugs"); expect(page.get_by_role("heading", name="没有匹配的药物档案")).to_be_visible()
                    passed("workspace switching reloads isolated API scope")
                    page.set_viewport_size({"width": 390, "height": 844}); page.reload()
                    page.get_by_role("button", name="打开导航").click()
                    expect(page.get_by_role("navigation")).to_be_visible()
                    page.screenshot(path=str(ROOT / "outputs/frontend-e2e-mobile.png"), full_page=True)
                    passed("mobile navigation")
                    page.set_viewport_size({"width": 1440, "height": 900})
                    page.goto(origin + "/workspace")
                    page.get_by_label("切换工作区").select_option(WORKSPACE)
                    page.wait_for_url(origin + "/")
                    page.goto(origin + "/workspace")
                    reviewer_option = page.get_by_label("游客演示账号").locator("option").filter(has_text="reviewer@pharmascope.invalid").first
                    page.get_by_label("游客演示账号").select_option(reviewer_option.get_attribute("value"))
                    page.get_by_role("button", name="保存演示账号").click()
                    expect(page.get_by_role("status")).to_contain_text("游客演示账号已更新")
                    demo_option = page.get_by_label("游客演示账号").locator("option").filter(has_text="analyst@pharmascope.invalid").first
                    page.get_by_label("游客演示账号").select_option(demo_option.get_attribute("value"))
                    page.get_by_role("button", name="保存演示账号").click()
                    expect(page.get_by_role("status")).to_contain_text("游客演示账号已更新")
                    passed("admin selects the account used for guest demonstration")
                    page.get_by_role("button", name="退出登录").click(); page.wait_for_url("**/login")
                    page.get_by_role("button", name="登录", exact=True).click()
                    page.wait_for_url(origin + "/")
                    expect(page.locator(".ps-mode-banner")).to_contain_text("游客只读模式")
                    expect(page.get_by_role("link", name="浙ICP备2026076087号-1")).to_be_visible()
                    page.goto(origin + "/drugs")
                    expect(page.get_by_role("link", name="Browser E2E Object", exact=True)).to_be_visible()
                    expect(page.get_by_role("button", name="＋ 建立药物档案")).to_have_count(0)
                    page.goto(origin + "/reports")
                    expect(page.get_by_role("heading", name="报告中心", exact=True)).to_be_visible()
                    expect(page.get_by_role("link", name="新建研究")).to_have_count(0)
                    page.goto(origin + "/inbox")
                    expect(page.get_by_role("button", name="全部标为已读")).to_have_count(0)
                    page.goto(origin + "/research/new")
                    expect(page.get_by_role("status")).to_contain_text("游客只能浏览演示数据")
                    expect(page.get_by_role("button", name="开始研究 →")).to_have_count(0)
                    page.goto(origin + "/workspace")
                    expect(page.get_by_role("status")).to_contain_text("游客只能浏览演示数据")
                    csrf = page.evaluate("sessionStorage.getItem('pharmascope_csrf')")
                    denied = context.request.post(origin + BASE_API + "/drugs", headers={"X-CSRF-Token": csrf}, data={"display_name": "Guest write denied"})
                    assert denied.status == 403, denied.text()
                    passed("guest sees selected account data, read-only UI, and server rejects writes")
                    assert not errors, errors
                    passed("no browser runtime errors; no localhost API URL in production chunks")
                    browser.close()
                result["success"] = True
            except Exception:
                output.flush(); output.seek(0); print(output.read()[-4000:], file=sys.stderr)
                raise
            finally:
                process.terminate()
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired: process.kill(); process.wait()
                results_dir = ROOT / "outputs"; results_dir.mkdir(exist_ok=True)
                (results_dir / "frontend-e2e-results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--serve": serve(int(sys.argv[2]))
    else: run()
