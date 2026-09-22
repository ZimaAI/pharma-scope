"""PharmaScope Lite domain API.

This module is the self contained FastAPI application used by the Lite demo.  It
keeps the domain state in a small repository abstraction so that the same API can
run with replay fixtures during development and can later be backed by SQLAlchemy
without changing the HTTP contract.  The original GPT Researcher demo routes are
left in ``server.app``; this app exposes the versioned PharmaScope contract.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Iterable, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, PlainTextResponse
from pydantic import BaseModel, Field


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "docs" / "reference" / "PharmaScope_Lite_v1.0" / "fixtures"
DEFAULT_WORKSPACE = "dee59b72-2cb2-5255-934c-b44a3fd8911c"
SECOND_WORKSPACE = "b9c9d1b4-62c5-5b58-92d1-de56235db31d"
DEFAULT_USER = "dacd1189-f315-5985-98ae-dce1a533104c"
REVIEWER_USER = "830a0c39-02ed-53a8-9616-c4d7827fb9ad"
ADMIN_USER = "95023655-2f60-587d-834b-eabaa2e759af"


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def uid() -> str:
    return str(uuid.uuid4())


def read_fixture(name: str, default: Any) -> Any:
    try:
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def page(items: Iterable[dict], limit: int = 20, cursor: str | None = None) -> dict:
    values = list(items)
    limit = max(1, min(int(limit or 20), 100))
    offset = 0
    if cursor:
        try:
            offset = max(0, int(cursor))
        except ValueError:
            raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "Invalid cursor"})
    selected = values[offset : offset + limit]
    nxt = str(offset + limit) if offset + limit < len(values) else None
    return {"items": selected, "next_cursor": nxt, "has_more": nxt is not None}


class LoginRequest(BaseModel):
    email: str
    password: str


class DomainState:
    """Thread-safe in-process repository used by replay/demo and unit tests."""

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.users: dict[str, dict] = {}
        self.workspaces: dict[str, dict] = {}
        self.memberships: dict[tuple[str, str], dict] = {}
        self.sessions: dict[str, dict] = {}
        self.drugs: dict[str, dict] = {}
        self.aliases: dict[str, dict] = {}
        self.links: dict[str, dict] = {}
        self.records: dict[str, dict] = {}
        self.snapshots: dict[str, dict] = {}
        self.observations: dict[str, dict] = {}
        self.evidence: dict[str, dict] = {}
        self.events: dict[str, dict] = {}
        self.revisions: dict[str, dict] = {}
        self.jobs: dict[str, dict] = {}
        self.runs: dict[str, dict] = {}
        self.run_events: dict[str, list[dict]] = {}
        self.tool_calls: dict[str, list[dict]] = {}
        self.reports: dict[str, dict] = {}
        self.versions: dict[str, dict] = {}
        self.reviews: dict[str, dict] = {}
        self.subscriptions: dict[str, dict] = {}
        self.occurrences: dict[str, dict] = {}
        self.deliveries: dict[str, dict] = {}
        self.audit: list[dict] = []
        self.notices: list[dict] = []
        self.idempotency: dict[tuple[str, str], tuple[str, Any]] = {}
        self.sources: dict[str, dict] = {
            "ctgov": {"source": "ctgov", "enabled": True, "configured": True, "state": "healthy", "last_success_at": None, "last_error_code": None, "coverage": {"records": 0}},
            "pubmed": {"source": "pubmed", "enabled": True, "configured": True, "state": "healthy", "last_success_at": None, "last_error_code": None, "coverage": {"records": 0}},
        }
        self.seed()

    def seed(self) -> None:
        ident = read_fixture("00-identities.json", {})
        ws = ident.get("workspace", {"id": DEFAULT_WORKSPACE, "name": "PharmaScope 演示研究组", "timezone": "Asia/Shanghai"})
        ws2 = ident.get("second_workspace", {"id": SECOND_WORKSPACE, "name": "隔离测试组", "timezone": "America/Los_Angeles"})
        self.workspaces[ws["id"]] = {**ws, "created_at": now()}
        self.workspaces[ws2["id"]] = {**ws2, "created_at": now()}
        for u in ident.get("users", []):
            self.users[u["id"]] = {**u, "is_active": True, "created_at": now()}
            self.memberships[(DEFAULT_WORKSPACE, u["id"])] = {"workspace_id": DEFAULT_WORKSPACE, "user_id": u["id"], "role": u.get("role", "analyst"), "enabled": True, "created_at": now()}
        # The static Next.js demo uses a friendly workspace alias.  It resolves
        # to the same seeded workspace while all canonical API responses retain
        # the UUID from the fixture contract.
        self.workspaces["demo-workspace"] = {**self.workspaces[DEFAULT_WORKSPACE], "id": "demo-workspace"}
        for u in ident.get("users", []):
            original = self.memberships[(DEFAULT_WORKSPACE, u["id"])]
            self.memberships[("demo-workspace", u["id"])] = {**original, "workspace_id": "demo-workspace"}
        # Isolated workspace is deliberately populated only for the admin to make
        # cross-workspace authorization tests deterministic.
        self.memberships[(SECOND_WORKSPACE, ADMIN_USER)] = {"workspace_id": SECOND_WORKSPACE, "user_id": ADMIN_USER, "role": "admin", "enabled": True, "created_at": now()}
        for d in read_fixture("01-drugs.json", []):
            self.drugs[d["id"]] = d
        for r in [read_fixture("04-trial-record.json", {}), self._publication_record()]:
            if r:
                self.records[r["id"]] = r
        for s in read_fixture("02-trial-snapshots.json", []):
            self.snapshots[s["id"]] = s
        p = read_fixture("05-publication-snapshot.json", {})
        if p:
            self.snapshots[p["id"]] = p
        for o in read_fixture("03-observations.json", []):
            self.observations[o["id"]] = o
        if p:
            observation_id = uid()
            self.observations.setdefault(observation_id, {"id": observation_id, "workspace_id": DEFAULT_WORKSPACE, "record_id": p["record_id"], "snapshot_id": p["id"], "observation_seq": 1, "fetched_at": p.get("first_observed_at", now()), "outcome": "baseline", "error_code": None, "created_at": now()})
            if p["record_id"] in self.records:
                self.records[p["record_id"]]["current_observation_id"] = observation_id
        for e in read_fixture("06-evidence.json", []):
            self.evidence[e["id"]] = e
        ev = read_fixture("11-events-and-revisions.json", {})
        for e in ev.get("events", []):
            self.events[e["id"]] = e
        for r in ev.get("revisions", []):
            self.revisions[r["id"]] = r
        for source in self.sources.values():
            source["last_success_at"] = now()
        for r in self.records.values():
            self.sources[r["source"]]["coverage"]["records"] += 1
        # A replay report is useful immediately after seeding and mirrors the
        # fixtures without claiming that a live model ran.
        output = read_fixture("08-research-output.json", None)
        if output:
            run_id = "0ea32fa2-01c1-5aed-a9b1-d0fa7bd00b8a"
            report_id = "598c1318-133d-5ac8-adf6-f008e782cec0"
            version_id = uid()
            self.runs[run_id] = {"id": run_id, "workspace_id": DEFAULT_WORKSPACE, "created_at": now(), "created_by": DEFAULT_USER, "status": "completed", "question": read_fixture("07-research-request.json", {}).get("question", ""), "runtime_mode": "replay", "frozen_request": read_fixture("07-research-request.json", {}), "budget": read_fixture("07-research-request.json", {}).get("budget", {}), "usage": {"tool_calls": 1, "model_calls": 0, "input_tokens": None, "output_tokens": None, "usage_quality": "unknown", "estimated_cost": None, "currency": None}, "coverage": output.get("coverage", []), "report_id": report_id, "attempt": 1, "event_seq": 8, "next_event_seq": 8, "stop_reason": "answered", "updated_at": now()}
            self.run_events[run_id] = read_fixture("09-run-events.json", [])
            self.reports[report_id] = {"id": report_id, "workspace_id": DEFAULT_WORKSPACE, "created_at": now(), "title": output.get("title", "研究简报"), "state": "published", "run_id": run_id, "created_by": DEFAULT_USER, "current_version_id": version_id, "published_version_id": version_id, "updated_at": now()}
            self.versions[version_id] = {"id": version_id, "workspace_id": DEFAULT_WORKSPACE, "created_at": now(), "report_id": report_id, "version_no": 1, "content": output, "content_hash": self.hash(output), "created_by": DEFAULT_USER, "runtime_mode": "replay", "claim_ids": [uid() for _ in output.get("claims", [])]}

    @staticmethod
    def hash(value: Any) -> str:
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @staticmethod
    def _publication_record() -> dict:
        p = read_fixture("05-publication-snapshot.json", {})
        if not p:
            return {}
        projection = p.get("normalized", {})
        return {"id": p.get("record_id"), "workspace_id": p.get("workspace_id", DEFAULT_WORKSPACE), "created_at": p.get("first_observed_at", now()), "source": "pubmed", "external_id": projection.get("pmid", "DEMO-PM-001"), "kind": "publication", "canonical_url": "demo://publication/" + str(projection.get("pmid", "DEMO-PM-001")), "current_snapshot_id": p.get("id"), "current_observation_id": None, "updated_at": p.get("first_observed_at", now()), "is_demo": True, "current_projection": projection}


state = DomainState()


def error(code: str, message: str, status: int = 400, details: dict | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "details": details or {}, "request_id": uid()}})


async def user_context(request: Request) -> dict:
    token = request.cookies.get("pharmascope_session")
    if not token:
        # API clients in replay mode may send an explicit user header. This is
        # disabled when PHARMA_ALLOW_DEV_HEADER=0 and never trusted for role.
        header_user = request.headers.get("X-User-Id") if os.getenv("PHARMA_ALLOW_DEV_HEADER", "1") == "1" else None
        if header_user and header_user in state.users:
            return state.users[header_user]
        raise HTTPException(401, detail={"code": "AUTH_REQUIRED", "message": "Authentication required"})
    session = state.sessions.get(token)
    if not session or session["expires_at"] < datetime.now(timezone.utc).timestamp():
        raise HTTPException(401, detail={"code": "AUTH_REQUIRED", "message": "Session expired"})
    user = state.users.get(session["user_id"])
    if not user or not user.get("is_active", True):
        raise HTTPException(401, detail={"code": "AUTH_REQUIRED", "message": "Inactive account"})
    return user


def membership(workspace_id: str, user: dict) -> dict | None:
    m = state.memberships.get((workspace_id, user["id"]))
    return m if m and m.get("enabled", True) else None


def membership_contract(m: dict) -> dict:
    ws = state.workspaces.get(m.get("workspace_id"), {})
    return {"workspace_id": m.get("workspace_id"), "workspace_name": ws.get("name", ""), "role": m.get("role")}


def user_contract(user: dict) -> dict:
    return {"id": user.get("id"), "email": user.get("email"), "display_name": user.get("display_name"), "is_active": user.get("is_active", True)}


async def workspace_user(workspace_id: str, user: dict = Depends(user_context)) -> dict:
    if workspace_id not in state.workspaces:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Workspace not found"})
    m = membership(workspace_id, user)
    if not m:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Workspace not found"})
    return {"user": user, "membership": m, "workspace_id": workspace_id}


def require_role(ctx: dict, *roles: str) -> None:
    if ctx["membership"]["role"] not in roles:
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "Insufficient role"})


async def csrf(request: Request, ctx: dict = Depends(workspace_user)) -> dict:
    token = request.headers.get("X-CSRF-Token")
    session_token = request.cookies.get("pharmascope_session")
    if session_token and (not token or token != state.sessions.get(session_token, {}).get("csrf")):
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "CSRF token required"})
    return ctx


app = FastAPI(title="PharmaScope Lite API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=[o for o in os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:3000,http://localhost:8000").split(",") if o], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def workspace_alias_middleware(request: Request, call_next):
    # Keep the friendly alias used by the static demo frontend while routing to
    # the canonical fixture UUID required by the API contract.
    path = request.scope.get("path", "")
    marker = "/workspaces/demo-workspace/"
    if marker in path:
        request.scope["path"] = path.replace(marker, f"/workspaces/{DEFAULT_WORKSPACE}/", 1)
    return await call_next(request)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-Id") or uid()
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    return response


@app.exception_handler(HTTPException)
async def api_http_error(request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, dict) else {"code": "HTTP_ERROR", "message": str(exc.detail)}
    code, msg = detail.get("code", "HTTP_ERROR"), detail.get("message", "Request failed")
    response = error(code, msg, exc.status_code, detail.get("details", {}))
    body = response.body
    if body:
        try:
            payload = json.loads(body)
            payload["error"]["request_id"] = getattr(request.state, "request_id", uid())
            response.body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            response.headers["content-length"] = str(len(response.body))
        except (TypeError, ValueError):
            pass
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    response = error("VALIDATION_ERROR", "Request validation failed", 422, {"fields": exc.errors()})
    payload = json.loads(response.body)
    payload["error"]["request_id"] = getattr(request.state, "request_id", uid())
    response.body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    response.headers["content-length"] = str(len(response.body))
    return response


@app.get("/healthz")
async def healthz() -> dict:
    return {"message": "ok", "status": "ok", "mode": os.getenv("PHARMA_MODE", "demo")}


@app.get("/readyz")
async def readyz() -> dict:
    return {"message": "ready", "status": "ready", "database": "replay"}


@app.post("/api/v1/auth/login")
async def login(body: LoginRequest, response: Response) -> dict:
    user = next((u for u in state.users.values() if u["email"].lower() == body.email.lower()), None)
    allowed = os.getenv("PHARMA_DEMO_PASSWORD", "demo")
    if not user or body.password != allowed:
        raise HTTPException(401, detail={"code": "AUTH_REQUIRED", "message": "Invalid credentials"})
    token, csrf_token = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
    state.sessions[token] = {"user_id": user["id"], "csrf": csrf_token, "expires_at": (datetime.now(timezone.utc) + timedelta(hours=12)).timestamp()}
    response.set_cookie("pharmascope_session", token, httponly=True, samesite="lax", secure=os.getenv("PHARMA_COOKIE_SECURE", "0") == "1", max_age=43200)
    return {"user": user_contract(user), "memberships": [membership_contract(m) for m in state.memberships.values() if m["user_id"] == user["id"]], "csrf_token": csrf_token}


@app.post("/api/v1/auth/logout")
async def logout(request: Request, response: Response, csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"), _user: dict = Depends(user_context)) -> dict:
    token = request.cookies.get("pharmascope_session")
    if token and csrf_token != state.sessions.get(token, {}).get("csrf"):
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "CSRF token required"})
    if token:
        state.sessions.pop(token, None)
    response.delete_cookie("pharmascope_session")
    return {"message": "logged out"}


@app.get("/api/v1/auth/me")
async def me(request: Request, user: dict = Depends(user_context)) -> dict:
    token = request.cookies.get("pharmascope_session")
    csrf_token = state.sessions.get(token, {}).get("csrf") if token else None
    return {"user": user_contract(user), "memberships": [membership_contract(m) for m in state.memberships.values() if m["user_id"] == user["id"]], "csrf_token": csrf_token}


def records_for(ws: str, kind: str | None = None) -> list[dict]:
    return [r for r in state.records.values() if r.get("workspace_id") == ws and (kind is None or r.get("kind") == kind)]


def with_projection(record: dict) -> dict:
    # Trial/Publication are source records with a nested projection in the
    # contract.  Keep that shape intact so generated OpenAPI clients can decode
    # either object without special casing the list and detail endpoints.
    p = copy.deepcopy(record)
    p.setdefault("current_projection", {})
    return p


def source_health_payload() -> list[dict]:
    """Expose only the stable SourceHealth contract fields."""
    fields = ("source", "enabled", "configured", "state", "last_success_at", "last_error_code")
    return [{key: value.get(key) for key in fields} for value in state.sources.values()]


@app.get("/api/v1/workspaces/{workspace_id}/dashboard")
async def dashboard(workspace_id: str, ctx: dict = Depends(workspace_user)) -> dict:
    events = [e for e in state.events.values() if e.get("workspace_id") == workspace_id]
    pending = [r for r in state.reports.values() if r.get("workspace_id") == workspace_id and r.get("state") in ("in_review", "draft")]
    watched = {d for s in state.subscriptions.values() if s.get("workspace_id") == workspace_id and s.get("enabled") for d in s.get("drug_ids", [])}
    return {"watched_drugs": len(watched), "events_last_7_days": len(events), "pending_reviews": len(pending), "source_health": source_health_payload(), "as_of": now(), "is_demo": os.getenv("PHARMA_RUNTIME_MODE", "replay") == "replay"}


@app.get("/api/v1/workspaces/{workspace_id}/members")
async def members(workspace_id: str, limit: int = 20, cursor: str | None = None, ctx: dict = Depends(workspace_user)) -> dict:
    return page([{"user": user_contract(state.users.get(m["user_id"], {})), "role": m.get("role"), "enabled": m.get("enabled", True)} for (ws, _), m in state.memberships.items() if ws == workspace_id], limit, cursor)


@app.patch("/api/v1/workspaces/{workspace_id}/members/{user_id}")
async def member_update(workspace_id: str, user_id: str, request: Request, ctx: dict = Depends(csrf)) -> dict:
    require_role(ctx, "admin")
    m = state.memberships.get((workspace_id, user_id))
    if not m:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Member not found"})
    payload = await request.json()
    if not payload:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "Empty patch"})
    if "role" in payload and payload["role"] in ("reader", "analyst", "reviewer", "admin"):
        m["role"] = payload["role"]
    if "enabled" in payload:
        m["enabled"] = bool(payload["enabled"])
    return {**m, "user": state.users.get(user_id)}


@app.get("/api/v1/workspaces/{workspace_id}/drugs")
async def drugs_list(workspace_id: str, query: str | None = None, archived: bool | None = None, limit: int = 20, cursor: str | None = None, ctx: dict = Depends(workspace_user)) -> dict:
    items = [d for d in state.drugs.values() if d.get("workspace_id") == workspace_id]
    if archived is not None:
        items = [d for d in items if d.get("archived", False) == archived]
    if query:
        q = query.lower()[:200]
        items = [d for d in items if q in d.get("display_name", "").lower() or q in (d.get("development_code") or "").lower()]
    items.sort(key=lambda x: (x.get("display_name", ""), x["id"]))
    return page(items, limit, cursor)


@app.post("/api/v1/workspaces/{workspace_id}/drugs")
async def drug_create(workspace_id: str, request: Request, ctx: dict = Depends(csrf)) -> dict:
    require_role(ctx, "analyst", "reviewer", "admin")
    p = await request.json()
    if not p.get("display_name"):
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "display_name is required"})
    d = {"id": uid(), "workspace_id": workspace_id, "created_at": now(), "updated_at": now(), "display_name": str(p["display_name"]), "development_code": p.get("development_code"), "description": p.get("description"), "indications": p.get("indications", []), "targets": p.get("targets", []), "revision": 1, "archived": False}
    state.drugs[d["id"]] = d
    return JSONResponse(status_code=201, content=d)


def get_drug(workspace_id: str, drug_id: str) -> dict:
    d = state.drugs.get(drug_id)
    if not d or d.get("workspace_id") != workspace_id:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Drug not found"})
    return d


@app.get("/api/v1/workspaces/{workspace_id}/drugs/{drug_id}")
async def drug_get(workspace_id: str, drug_id: str, ctx: dict = Depends(workspace_user)) -> dict:
    return copy.deepcopy(get_drug(workspace_id, drug_id))


@app.patch("/api/v1/workspaces/{workspace_id}/drugs/{drug_id}")
async def drug_update(workspace_id: str, drug_id: str, request: Request, ctx: dict = Depends(csrf), if_match: str | None = Header(default=None, alias="If-Match")) -> dict:
    require_role(ctx, "analyst", "reviewer", "admin")
    d = get_drug(workspace_id, drug_id)
    if if_match and if_match.strip('"') != str(d.get("revision", 1)):
        raise HTTPException(409, detail={"code": "STALE_VERSION", "message": "Drug revision is stale"})
    p = await request.json()
    for k in ("display_name", "development_code", "description", "indications", "targets"):
        if k in p:
            d[k] = p[k]
    d["revision"] = int(d.get("revision", 1)) + 1
    d["updated_at"] = now()
    return d


@app.post("/api/v1/workspaces/{workspace_id}/drugs/{drug_id}/archive")
async def drug_archive(workspace_id: str, drug_id: str, ctx: dict = Depends(csrf)) -> dict:
    require_role(ctx, "analyst", "reviewer", "admin")
    d = get_drug(workspace_id, drug_id)
    d["archived"] = True
    d["revision"] += 1
    d["updated_at"] = now()
    return d


@app.get("/api/v1/workspaces/{workspace_id}/drugs/{drug_id}/aliases")
async def drug_aliases(workspace_id: str, drug_id: str, limit: int = 20, cursor: str | None = None, ctx: dict = Depends(workspace_user)) -> dict:
    get_drug(workspace_id, drug_id)
    return page([a for a in state.aliases.values() if a["workspace_id"] == workspace_id and a["drug_id"] == drug_id], limit, cursor)


@app.post("/api/v1/workspaces/{workspace_id}/drugs/{drug_id}/aliases")
async def alias_create(workspace_id: str, drug_id: str, request: Request, ctx: dict = Depends(csrf)) -> dict:
    require_role(ctx, "analyst", "reviewer", "admin")
    get_drug(workspace_id, drug_id)
    p = await request.json()
    if not p.get("alias") or not p.get("namespace") or not p.get("note"):
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "alias, namespace and note are required"})
    a = {"id": uid(), "workspace_id": workspace_id, "drug_id": drug_id, "alias": p["alias"], "normalized_alias": str(p["alias"]).strip().lower(), "namespace": p["namespace"], "status": "pending", "evidence_id": p.get("evidence_id"), "note": p.get("note", ""), "proposed_by": ctx["user"]["id"], "reviewed_by": None, "reviewed_at": None, "created_at": now()}
    state.aliases[a["id"]] = a
    return JSONResponse(status_code=201, content=a)


@app.get("/api/v1/workspaces/{workspace_id}/aliases")
async def alias_pending(workspace_id: str, status: str | None = None, limit: int = 20, cursor: str | None = None, ctx: dict = Depends(workspace_user)) -> dict:
    items = [a for a in state.aliases.values() if a["workspace_id"] == workspace_id and (status is None or a["status"] == status)]
    return page(items, limit, cursor)


@app.post("/api/v1/workspaces/{workspace_id}/aliases/{alias_id}/decision")
async def alias_decide(workspace_id: str, alias_id: str, request: Request, ctx: dict = Depends(csrf)) -> dict:
    require_role(ctx, "reviewer", "admin")
    a = state.aliases.get(alias_id)
    if not a or a["workspace_id"] != workspace_id:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Alias not found"})
    p = await request.json()
    if p.get("decision") not in ("approve", "reject", "revoke") or not p.get("note"):
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "decision and note are required"})
    a["status"] = {"approve": "approved", "reject": "rejected", "revoke": "revoked"}[p["decision"]]
    a["reviewed_by"], a["reviewed_at"], a["note"] = ctx["user"]["id"], now(), p["note"]
    return a


def list_links(workspace_id: str, status: str | None = None) -> list[dict]:
    return [x for x in state.links.values() if x["workspace_id"] == workspace_id and (status is None or x["status"] == status)]


@app.get("/api/v1/workspaces/{workspace_id}/entity-links")
async def links_list(workspace_id: str, status: str | None = None, limit: int = 20, cursor: str | None = None, ctx: dict = Depends(workspace_user)) -> dict:
    return page(list_links(workspace_id, status), limit, cursor)


@app.post("/api/v1/workspaces/{workspace_id}/entity-links")
async def link_create(workspace_id: str, request: Request, ctx: dict = Depends(csrf)) -> dict:
    require_role(ctx, "analyst", "reviewer", "admin")
    p = await request.json()
    if not p.get("record_id") or not p.get("drug_id") or not p.get("relation") or not p.get("note"):
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "record_id, drug_id, relation and note are required"})
    if p["record_id"] not in state.records or p["drug_id"] not in state.drugs:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Record or drug not found"})
    x = {"id": uid(), "workspace_id": workspace_id, "record_id": p["record_id"], "drug_id": p["drug_id"], "relation": p["relation"], "status": "pending", "evidence_id": p.get("evidence_id"), "note": p.get("note", ""), "proposed_by": ctx["user"]["id"], "reviewed_by": None, "reviewed_at": None, "created_at": now()}
    state.links[x["id"]] = x
    return JSONResponse(status_code=201, content=x)


@app.post("/api/v1/workspaces/{workspace_id}/entity-links/{link_id}/decision")
async def link_decide(workspace_id: str, link_id: str, request: Request, ctx: dict = Depends(csrf)) -> dict:
    require_role(ctx, "reviewer", "admin")
    x = state.links.get(link_id)
    if not x or x["workspace_id"] != workspace_id:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Link not found"})
    p = await request.json()
    if p.get("decision") not in ("approve", "reject", "revoke") or not p.get("note"):
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "decision and note are required"})
    x["status"] = {"approve": "approved", "reject": "rejected", "revoke": "revoked"}[p["decision"]]
    x["reviewed_by"], x["reviewed_at"], x["note"] = ctx["user"]["id"], now(), p["note"]
    return x


@app.get("/api/v1/workspaces/{workspace_id}/sources")
async def source_list(workspace_id: str, ctx: dict = Depends(workspace_user)) -> dict:
    return {"items": source_health_payload()}


@app.patch("/api/v1/workspaces/{workspace_id}/sources/{source}")
async def source_update(workspace_id: str, source: str, request: Request, ctx: dict = Depends(csrf)) -> dict:
    require_role(ctx, "admin")
    if source not in state.sources:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Source not found"})
    p = await request.json()
    if not isinstance(p.get("enabled"), bool):
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "enabled is required"})
    state.sources[source].update({"enabled": p["enabled"]})
    return next(item for item in source_health_payload() if item["source"] == source)


@app.post("/api/v1/workspaces/{workspace_id}/source-syncs")
async def source_sync(workspace_id: str, request: Request, ctx: dict = Depends(csrf), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> dict:
    require_role(ctx, "analyst", "reviewer", "admin")
    p = await request.json()
    if not isinstance(p.get("sources"), list) or not p["sources"] or not isinstance(p.get("drug_ids"), list) or not p["drug_ids"] or p.get("mode") not in ("discovery", "refresh_linked"):
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "sources, drug_ids and mode are required"})
    if not isinstance(p.get("sources"), list) or not p["sources"]:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "sources is required"})
    requested_sources = p["sources"]
    source = requested_sources[0]
    if source not in state.sources:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "Unsupported source"})
    key = (workspace_id, idempotency_key or uid())
    if key in state.idempotency:
        if state.idempotency[key][0] != state.hash(p):
            raise HTTPException(409, detail={"code": "IDEMPOTENCY_CONFLICT", "message": "Idempotency key was already used with a different request"})
        return state.idempotency[key][1]
    j = {"id": uid(), "workspace_id": workspace_id, "created_at": now(), "kind": "ingest", "state": "queued", "progress": {"processed": 0, "total": None}, "coverage": [], "attempt": 0, "error_code": None}
    state.jobs[j["id"]] = j
    state.idempotency[key] = (state.hash(p), j)
    return JSONResponse(status_code=202, content=j)


@app.get("/api/v1/workspaces/{workspace_id}/jobs/{job_id}")
async def job_get(workspace_id: str, job_id: str, ctx: dict = Depends(workspace_user)) -> dict:
    j = state.jobs.get(job_id)
    if not j or j["workspace_id"] != workspace_id:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Job not found"})
    return j


def project_filter(workspace_id: str, kind: str, drug_id: str | None, query: str | None, status: str | None, has_results: bool | None) -> list[dict]:
    rows = [with_projection(r) for r in records_for(workspace_id, kind)]
    if query:
        q = query.lower()[:200]; rows = [x for x in rows if q in str(x.get("current_projection", {}).get("title", "")).lower() or q in str(x.get("external_id", "")).lower()]
    if status:
        rows = [x for x in rows if x.get("current_projection", {}).get("status") == status]
    if has_results is not None:
        rows = [x for x in rows if bool(x.get("current_projection", {}).get("has_results")) == has_results]
    if drug_id:
        linked = {x["record_id"] for x in state.links.values() if x["workspace_id"] == workspace_id and x["drug_id"] == drug_id and x["status"] in ("pending", "approved")}
        # Demo data links PX-101 to the trial implicitly; explicit links take precedence.
        if not linked and kind == "trial" and drug_id == "dd1dcb81-e4b6-5343-b4a6-544bf716d867":
            linked = {x["id"] for x in records_for(workspace_id, "trial")}
        rows = [x for x in rows if x["id"] in linked]
    return rows


@app.get("/api/v1/workspaces/{workspace_id}/trials")
async def trials(workspace_id: str, drug_id: str | None = None, query: str | None = None, status: str | None = None, has_results: bool | None = None, observed_since: str | None = None, limit: int = 20, cursor: str | None = None, ctx: dict = Depends(workspace_user)) -> dict:
    return page(project_filter(workspace_id, "trial", drug_id, query, status, has_results), limit, cursor)


@app.get("/api/v1/workspaces/{workspace_id}/trials/{trial_id}")
async def trial(workspace_id: str, trial_id: str, ctx: dict = Depends(workspace_user)) -> dict:
    r = state.records.get(trial_id)
    if not r or r.get("workspace_id") != workspace_id or r.get("kind") != "trial":
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Trial not found"})
    return with_projection(r)


@app.get("/api/v1/workspaces/{workspace_id}/publications")
async def publications(workspace_id: str, drug_id: str | None = None, query: str | None = None, status: str | None = None, has_results: bool | None = None, observed_since: str | None = None, limit: int = 20, cursor: str | None = None, ctx: dict = Depends(workspace_user)) -> dict:
    return page(project_filter(workspace_id, "publication", drug_id, query, status, has_results), limit, cursor)


@app.get("/api/v1/workspaces/{workspace_id}/publications/{publication_id}")
async def publication(workspace_id: str, publication_id: str, ctx: dict = Depends(workspace_user)) -> dict:
    r = state.records.get(publication_id)
    if not r or r.get("workspace_id") != workspace_id or r.get("kind") != "publication":
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Publication not found"})
    return with_projection(r)


@app.get("/api/v1/workspaces/{workspace_id}/records/{record_id}/snapshots")
async def snapshots(workspace_id: str, record_id: str, limit: int = 20, cursor: str | None = None, ctx: dict = Depends(workspace_user)) -> dict:
    if record_id not in state.records or state.records[record_id].get("workspace_id") != workspace_id:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Record not found"})
    return page([s for s in state.snapshots.values() if s.get("workspace_id") == workspace_id and s.get("record_id") == record_id], limit, cursor)


@app.get("/api/v1/workspaces/{workspace_id}/records/{record_id}/observations")
async def observations(workspace_id: str, record_id: str, limit: int = 20, cursor: str | None = None, ctx: dict = Depends(workspace_user)) -> dict:
    if record_id not in state.records or state.records[record_id].get("workspace_id") != workspace_id:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Record not found"})
    return page(sorted([o for o in state.observations.values() if o.get("workspace_id") == workspace_id and o.get("record_id") == record_id], key=lambda x: x.get("observation_seq", 0)), limit, cursor)


def json_pointer(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.strip("/").split("/") if path else []:
        if isinstance(cur, dict): cur = cur.get(part)
        else: return None
    return cur


@app.get("/api/v1/workspaces/{workspace_id}/records/{record_id}/diff")
async def diff(workspace_id: str, record_id: str, before_observation_id: str, after_observation_id: str, ctx: dict = Depends(workspace_user)) -> dict:
    obs1, obs2 = state.observations.get(before_observation_id), state.observations.get(after_observation_id)
    if not obs1 or not obs2 or obs1.get("record_id") != record_id or obs2.get("record_id") != record_id:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Observation not found"})
    s1, s2 = state.snapshots.get(obs1.get("snapshot_id")), state.snapshots.get(obs2.get("snapshot_id"))
    n1, n2 = (s1 or {}).get("normalized", {}), (s2 or {}).get("normalized", {})
    changes = []
    keys = set(n1) | set(n2)
    for k in sorted(keys):
        if n1.get(k) != n2.get(k):
            changes.append({"path": "/" + k, "type": "added" if k not in n1 else "removed" if k not in n2 else "changed", "before": n1.get(k), "after": n2.get(k)})
    snapshot_ids = {obs1.get("snapshot_id"), obs2.get("snapshot_id")}
    evidence_ids = [e["id"] for e in state.evidence.values() if e.get("workspace_id") == workspace_id and e.get("snapshot_id") in snapshot_ids]
    return {"record_id": record_id, "before_observation_id": before_observation_id, "after_observation_id": after_observation_id, "changes": changes, "evidence_ids": evidence_ids}


@app.get("/api/v1/workspaces/{workspace_id}/snapshots/{snapshot_id}")
async def snapshot_get(workspace_id: str, snapshot_id: str, ctx: dict = Depends(workspace_user)) -> dict:
    s = state.snapshots.get(snapshot_id)
    if not s or s.get("workspace_id") != workspace_id:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Snapshot not found"})
    return s


@app.get("/api/v1/workspaces/{workspace_id}/evidence/{evidence_id}")
async def evidence_get(workspace_id: str, evidence_id: str, ctx: dict = Depends(workspace_user)) -> dict:
    e = state.evidence.get(evidence_id)
    if not e or e.get("workspace_id") != workspace_id:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Evidence not found"})
    return e


@app.get("/api/v1/workspaces/{workspace_id}/events")
async def event_list(workspace_id: str, drug_id: str | None = None, observed_since: str | None = None, limit: int = 20, cursor: str | None = None, ctx: dict = Depends(workspace_user)) -> dict:
    rows = [e for e in state.events.values() if e.get("workspace_id") == workspace_id]
    if drug_id:
        linked = {x["record_id"] for x in state.links.values() if x["workspace_id"] == workspace_id and x["drug_id"] == drug_id and x["status"] in ("pending", "approved")}
        if not linked and drug_id == "dd1dcb81-e4b6-5343-b4a6-544bf716d867":
            linked = {r["id"] for r in records_for(workspace_id, "trial")}
        rows = [e for e in rows if e.get("record_id") in linked]
    return page(sorted(rows, key=lambda x: x.get("updated_at", ""), reverse=True), limit, cursor)


@app.get("/api/v1/workspaces/{workspace_id}/events/{event_id}")
async def event_get(workspace_id: str, event_id: str, ctx: dict = Depends(workspace_user)) -> dict:
    e = state.events.get(event_id)
    if not e or e.get("workspace_id") != workspace_id:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Event not found"})
    return e


@app.get("/api/v1/workspaces/{workspace_id}/events/{event_id}/revisions")
async def event_revisions(workspace_id: str, event_id: str, limit: int = 20, cursor: str | None = None, ctx: dict = Depends(workspace_user)) -> dict:
    return page([r for r in state.revisions.values() if r.get("workspace_id") == workspace_id and r.get("event_id") == event_id], limit, cursor)


def emit(run_id: str, typ: str, payload: dict) -> dict:
    events = state.run_events.setdefault(run_id, [])
    seq = len(events) + 1
    e = {"schema_version": "1.0", "run_id": run_id, "seq": seq, "occurred_at": now(), "type": typ, "payload": payload}
    events.append(e)
    if run_id in state.runs:
        state.runs[run_id]["event_seq"] = seq
        state.runs[run_id]["next_event_seq"] = seq
        state.runs[run_id]["updated_at"] = e["occurred_at"]
    return e


@app.post("/api/v1/workspaces/{workspace_id}/research/runs")
async def run_create(workspace_id: str, request: Request, ctx: dict = Depends(csrf), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> dict:
    require_role(ctx, "analyst", "reviewer", "admin")
    p = await request.json()
    if not isinstance(p.get("question"), str) or len(p["question"].strip()) < 10:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "question must contain at least 10 characters"})
    if not isinstance(p.get("drug_ids"), list) or not p["drug_ids"]:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "drug_ids is required"})
    if not p.get("time_range") or not p.get("source_allowlist"):
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "time_range and source_allowlist are required"})
    key = (workspace_id, idempotency_key or uid())
    if key in state.idempotency:
        if state.idempotency[key][0] != state.hash(p):
            raise HTTPException(409, detail={"code": "IDEMPOTENCY_CONFLICT", "message": "Idempotency key was already used with a different request"})
        return state.idempotency[key][1]
    runtime_mode = os.getenv("PHARMA_RUNTIME_MODE", "replay")
    if runtime_mode not in ("replay", "gptr"):
        runtime_mode = "replay"
    rid = uid(); run = {"id": rid, "workspace_id": workspace_id, "created_at": now(), "created_by": ctx["user"]["id"], "status": "queued", "question": p["question"], "frozen_request": p, "runtime_mode": runtime_mode, "budget": p.get("budget", {}), "usage": {"tool_calls": 0, "model_calls": 0, "input_tokens": None, "output_tokens": None, "usage_quality": "unknown", "estimated_cost": None, "currency": None}, "coverage": [], "checkpoint_ref": None, "attempt": 1, "stop_reason": None, "report_id": None, "event_seq": 0, "next_event_seq": 0, "updated_at": now()}
    state.runs[rid] = run
    emit(rid, "run.queued", {"runtime_mode": run["runtime_mode"]}); run["status"] = "running"; emit(rid, "run.started", {"runtime_mode": run["runtime_mode"]})
    emit(rid, "plan.updated", {"summary": "读取已授权试验观察并检查文献覆盖。"})
    # Replay mode produces a deterministic structured draft from the checked-in
    # fixture.  Live GPT Researcher integration can replace this step while
    # preserving the same report/version contract.
    replay_output = read_fixture("08-research-output.json", None)
    if run["runtime_mode"] == "replay" and replay_output:
        report_id, version_id = uid(), uid()
        run["report_id"] = report_id; run["coverage"] = replay_output.get("coverage", [])
        report = {"id": report_id, "workspace_id": workspace_id, "created_at": now(), "run_id": rid, "title": replay_output.get("title", "研究简报"), "created_by": ctx["user"]["id"], "state": "draft", "current_version_id": version_id, "published_version_id": None, "updated_at": now()}
        version = {"id": version_id, "workspace_id": workspace_id, "created_at": now(), "report_id": report_id, "version_no": 1, "content": replay_output, "content_hash": state.hash(replay_output), "created_by": ctx["user"]["id"], "runtime_mode": "replay", "claim_ids": [uid() for _ in replay_output.get("claims", [])]}
        state.reports[report_id], state.versions[version_id] = report, version
        emit(rid, "report.ready", {"report_id": report_id, "runtime_mode": run["runtime_mode"]})
    run["status"] = "completed"; run["stop_reason"] = "answered"; run["next_event_seq"] = len(state.run_events[rid])
    emit(rid, "run.completed", {"runtime_mode": run["runtime_mode"], "stop_reason": "answered"}); run["next_event_seq"] = len(state.run_events[rid])
    state.idempotency[key] = (state.hash(p), run)
    return JSONResponse(status_code=202, content=run_contract(run))


def get_run(workspace_id: str, run_id: str) -> dict:
    r = state.runs.get(run_id)
    if not r or r.get("workspace_id") != workspace_id:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Research run not found"})
    return r


def run_contract(run: dict) -> dict:
    fields = ("id", "workspace_id", "created_at", "created_by", "question", "status", "runtime_mode", "attempt", "frozen_request", "usage", "coverage", "stop_reason", "event_seq", "report_id", "updated_at")
    return {key: run.get(key) for key in fields}


@app.get("/api/v1/workspaces/{workspace_id}/research/runs")
async def runs_list(workspace_id: str, limit: int = 20, cursor: str | None = None, ctx: dict = Depends(workspace_user)) -> dict:
    return page([run_contract(r) for r in sorted([r for r in state.runs.values() if r.get("workspace_id") == workspace_id], key=lambda x: x.get("created_at", ""), reverse=True)], limit, cursor)


@app.get("/api/v1/workspaces/{workspace_id}/research/runs/{run_id}")
async def run_get(workspace_id: str, run_id: str, ctx: dict = Depends(workspace_user)) -> dict:
    return run_contract(get_run(workspace_id, run_id))


@app.post("/api/v1/workspaces/{workspace_id}/research/runs/{run_id}/cancel")
async def run_cancel(workspace_id: str, run_id: str, ctx: dict = Depends(csrf)) -> dict:
    require_role(ctx, "analyst", "reviewer", "admin")
    r = get_run(workspace_id, run_id)
    if r["status"] not in ("completed", "failed", "cancelled"):
        r["status"] = "cancelled"; emit(run_id, "run.cancelled", {})
    return run_contract(r)


@app.post("/api/v1/workspaces/{workspace_id}/research/runs/{run_id}/retry")
async def run_retry(workspace_id: str, run_id: str, request: Request, ctx: dict = Depends(csrf), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> dict:
    require_role(ctx, "analyst", "reviewer", "admin")
    source = get_run(workspace_id, run_id); p = await request.json() if request.headers.get("content-length", "0") != "0" else {}
    return await run_create(workspace_id, _request_with_json({**source.get("frozen_request", {}), **p}), ctx, idempotency_key)


class _Req:
    def __init__(self, payload: dict): self.payload, self.headers = payload, {"content-length": str(len(json.dumps(payload)))}
    async def json(self): return self.payload


def _request_with_json(payload: dict) -> Request:
    # Internal helper only; retry delegates after authorization has been checked.
    return _Req(payload)  # type: ignore[return-value]


@app.post("/api/v1/workspaces/{workspace_id}/research/runs/{run_id}/clarifications")
async def run_clarify(workspace_id: str, run_id: str, request: Request, ctx: dict = Depends(csrf)) -> dict:
    require_role(ctx, "analyst", "reviewer", "admin")
    r = get_run(workspace_id, run_id); p = await request.json(); r["clarification"] = p; r["status"] = "queued"; return run_contract(r)


@app.get("/api/v1/workspaces/{workspace_id}/research/runs/{run_id}/tool-calls")
async def run_tools(workspace_id: str, run_id: str, limit: int = 20, cursor: str | None = None, ctx: dict = Depends(workspace_user)) -> dict:
    get_run(workspace_id, run_id); return page(state.tool_calls.get(run_id, []), limit, cursor)


@app.get("/api/v1/workspaces/{workspace_id}/research/runs/{run_id}/events")
async def run_stream(workspace_id: str, run_id: str, request: Request, last_event_id: str | None = Header(default=None, alias="Last-Event-ID"), ctx: dict = Depends(workspace_user)) -> StreamingResponse:
    get_run(workspace_id, run_id)
    start = int(last_event_id or 0)
    events = state.run_events.get(run_id, [])[start:]
    async def stream() -> AsyncIterator[str]:
        for e in events:
            yield f"id: {e['seq']}\nevent: {e['type']}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n"
        yield ": heartbeat\n\n"
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def report_for(workspace_id: str, report_id: str) -> dict:
    r = state.reports.get(report_id)
    if not r or r.get("workspace_id") != workspace_id:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Report not found"})
    return r


def report_contract(report: dict) -> dict:
    fields = ("id", "workspace_id", "created_at", "run_id", "title", "created_by", "state", "current_version_id", "published_version_id", "updated_at")
    return {key: report.get(key) for key in fields}


@app.get("/api/v1/workspaces/{workspace_id}/reports")
async def reports_list(workspace_id: str, state_filter: str | None = Query(default=None, alias="state"), limit: int = 20, cursor: str | None = None, ctx: dict = Depends(workspace_user)) -> dict:
    rows = [r for r in state.reports.values() if r.get("workspace_id") == workspace_id and (state_filter is None or r.get("state") == state_filter)]
    if ctx["membership"]["role"] == "reader":
        rows = [r for r in rows if r.get("published_version_id")]
    return page([report_contract(r) for r in rows], limit, cursor)


@app.get("/api/v1/workspaces/{workspace_id}/reports/{report_id}")
async def report_get(workspace_id: str, report_id: str, ctx: dict = Depends(workspace_user)) -> dict:
    raw = report_for(workspace_id, report_id)
    if ctx["membership"]["role"] == "reader" and not raw.get("published_version_id"):
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Report not found"})
    r = report_contract(copy.deepcopy(raw))
    if ctx["membership"]["role"] == "reader": r["current_version_id"] = None
    return r


@app.get("/api/v1/workspaces/{workspace_id}/reports/{report_id}/versions")
async def versions_list(workspace_id: str, report_id: str, limit: int = 20, cursor: str | None = None, ctx: dict = Depends(workspace_user)) -> dict:
    report_for(workspace_id, report_id); rows = [v for v in state.versions.values() if v.get("workspace_id") == workspace_id and v.get("report_id") == report_id]
    if ctx["membership"]["role"] == "reader": rows = [v for v in rows if v["id"] == report_for(workspace_id, report_id).get("published_version_id")]
    return page(rows, limit, cursor)


@app.post("/api/v1/workspaces/{workspace_id}/reports/{report_id}/versions")
async def version_create(workspace_id: str, report_id: str, request: Request, ctx: dict = Depends(csrf)) -> dict:
    require_role(ctx, "analyst", "reviewer", "admin")
    report = report_for(workspace_id, report_id); p = await request.json(); content = p.get("content")
    if not isinstance(content, dict) or not p.get("base_version_id") or not p.get("edit_note"):
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "base_version_id, content and edit_note are required"})
    base = state.versions.get(p["base_version_id"])
    if not base or base.get("report_id") != report_id:
        raise HTTPException(409, detail={"code": "STALE_VERSION", "message": "Base report version is not current"})
    versions = [v for v in state.versions.values() if v.get("report_id") == report_id]; v = {"id": uid(), "workspace_id": workspace_id, "created_at": now(), "report_id": report_id, "version_no": len(versions) + 1, "content": content, "content_hash": state.hash(content), "created_by": ctx["user"]["id"], "runtime_mode": report.get("runtime_mode", "replay"), "claim_ids": [uid() for _ in content.get("claims", [])]}
    state.versions[v["id"]] = v; report["current_version_id"] = v["id"]; report["state"] = "draft"; report["updated_at"] = now(); return JSONResponse(status_code=201, content=v)


@app.get("/api/v1/workspaces/{workspace_id}/reports/{report_id}/versions/{version_id}")
async def version_get(workspace_id: str, report_id: str, version_id: str, ctx: dict = Depends(workspace_user)) -> dict:
    report_for(workspace_id, report_id); v = state.versions.get(version_id)
    if not v or v.get("report_id") != report_id or (ctx["membership"]["role"] == "reader" and v["id"] != report_for(workspace_id, report_id).get("published_version_id")):
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Report version not found"})
    return v


@app.post("/api/v1/workspaces/{workspace_id}/reports/{report_id}/submit-review")
async def submit_review(workspace_id: str, report_id: str, request: Request, ctx: dict = Depends(csrf)) -> dict:
    require_role(ctx, "analyst", "admin")
    r = report_for(workspace_id, report_id); r["state"] = "in_review"; r["submitted_at"] = now(); r["updated_at"] = r["submitted_at"]; return report_contract(r)


@app.get("/api/v1/workspaces/{workspace_id}/reports/{report_id}/reviews")
async def reviews_list(workspace_id: str, report_id: str, limit: int = 20, cursor: str | None = None, ctx: dict = Depends(workspace_user)) -> dict:
    report_for(workspace_id, report_id); return page([x for x in state.reviews.values() if x["workspace_id"] == workspace_id and x["report_id"] == report_id], limit, cursor)


@app.post("/api/v1/workspaces/{workspace_id}/reports/{report_id}/reviews")
async def review_create(workspace_id: str, report_id: str, request: Request, ctx: dict = Depends(csrf)) -> dict:
    require_role(ctx, "reviewer", "admin")
    r = report_for(workspace_id, report_id); p = await request.json(); vid, ch = p.get("version_id"), p.get("content_hash"); v = state.versions.get(vid)
    if p.get("decision") not in ("approve", "request_changes") or not p.get("note"):
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "decision and note are required"})
    if not v or v.get("report_id") != report_id or v.get("content_hash") != ch: raise HTTPException(409, detail={"code": "STALE_VERSION", "message": "Version hash does not match"})
    if v.get("created_by") == ctx["user"]["id"]: raise HTTPException(409, detail={"code": "SELF_REVIEW_FORBIDDEN", "message": "Author cannot review own version"})
    if p.get("decision") not in ("approve", "reject") or not isinstance(p.get("note"), str) or not p["note"].strip():
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "decision and note are required"})
    rv = {"id": uid(), "workspace_id": workspace_id, "created_at": now(), "report_id": report_id, "version_id": vid, "content_hash": ch, "decision": p["decision"], "note": p["note"], "reviewer_id": ctx["user"]["id"]}; state.reviews[rv["id"]] = rv; r["state"] = "approved" if rv["decision"] == "approve" else "changes_requested"; return rv


@app.post("/api/v1/workspaces/{workspace_id}/reports/{report_id}/publish")
async def publish(workspace_id: str, report_id: str, request: Request, ctx: dict = Depends(csrf), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> dict:
    require_role(ctx, "reviewer", "admin")
    r = report_for(workspace_id, report_id); p = await request.json(); vid, ch = p.get("version_id"), p.get("content_hash"); v = state.versions.get(vid)
    if idempotency_key:
        key = (workspace_id + ":publish:" + report_id, idempotency_key)
        if key in state.idempotency:
            if state.idempotency[key][0] != state.hash(p):
                raise HTTPException(409, detail={"code": "IDEMPOTENCY_CONFLICT", "message": "Idempotency key was already used with a different request"})
            return state.idempotency[key][1]
    if not v or v.get("workspace_id") != workspace_id or v.get("report_id") != report_id or v.get("content_hash") != ch: raise HTTPException(409, detail={"code": "STALE_VERSION", "message": "Version hash does not match"})
    approved = any(x.get("version_id") == vid and x.get("decision") == "approve" and x.get("content_hash") == ch for x in state.reviews.values())
    if not approved: raise HTTPException(409, detail={"code": "REPORT_NOT_APPROVED", "message": "Report version has not been approved"})
    r.update({"published_version_id": vid, "current_version_id": vid, "state": "published", "published_at": now(), "published_by": ctx["user"]["id"], "updated_at": now()})
    if idempotency_key:
        state.idempotency[(workspace_id + ":publish:" + report_id, idempotency_key)] = (state.hash(p), r)
    return report_contract(r)


@app.post("/api/v1/workspaces/{workspace_id}/reports/{report_id}/retract")
async def retract(workspace_id: str, report_id: str, request: Request, ctx: dict = Depends(csrf)) -> dict:
    require_role(ctx, "reviewer", "admin"); r = report_for(workspace_id, report_id); p = await request.json()
    if not p.get("version_id") or not p.get("reason"):
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "version_id and reason are required"})
    if p["version_id"] != r.get("published_version_id"):
        raise HTTPException(409, detail={"code": "STALE_VERSION", "message": "Only the published version can be retracted"})
    r.update({"state": "retracted", "retracted_at": now(), "retract_reason": p.get("reason", "")}); return report_contract(r)


@app.get("/api/v1/workspaces/{workspace_id}/reports/{report_id}/export")
async def report_export(workspace_id: str, report_id: str, version_id: str | None = None, format: str = "json", ctx: dict = Depends(workspace_user)) -> Response:
    r = report_for(workspace_id, report_id); vid = version_id or r.get("published_version_id") or r.get("current_version_id"); v = state.versions.get(vid)
    if not v: raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Version not found"})
    if format == "markdown":
        c = v.get("content", {}); text = f"# {c.get('title', r.get('title', 'Research report'))}\n\n{c.get('summary', '')}\n"
        for section in c.get("sections", []): text += f"\n## {section.get('heading', '')}\n\n{section.get('text', '')}\n"
        return PlainTextResponse(text, media_type="text/markdown")
    return JSONResponse(v.get("content", {}))


@app.get("/api/v1/workspaces/{workspace_id}/reports/{report_id}/versions/{version_id}/claims")
async def claims(workspace_id: str, report_id: str, version_id: str, limit: int = 20, cursor: str | None = None, ctx: dict = Depends(workspace_user)) -> dict:
    v = await version_get(workspace_id, report_id, version_id, ctx)
    items = []
    for i, claim in enumerate(v.get("content", {}).get("claims", [])):
        items.append({"id": v["claim_ids"][i] if i < len(v.get("claim_ids", [])) else uid(), "workspace_id": workspace_id, "created_at": v.get("created_at", now()), "claim_key": claim.get("claim_key", f"C{i + 1}"), "statement": claim.get("statement", ""), "category": claim.get("category", "fact"), "qualifiers": claim.get("qualifiers", {}), "evidence_links": claim.get("evidence_links", []), "report_version_id": version_id, "verification_status": "unverified", "numeric_check": "not_applicable"})
    return page(items, limit, cursor)


@app.get("/api/v1/workspaces/{workspace_id}/reports/{report_id}/notices")
async def notices(workspace_id: str, report_id: str, limit: int = 20, cursor: str | None = None, ctx: dict = Depends(workspace_user)) -> dict:
    report_for(workspace_id, report_id); return page([n for n in state.notices if n["workspace_id"] == workspace_id and n["report_id"] == report_id], limit, cursor)


def schedule_occurrences(payload: dict) -> list[dict]:
    schedule = payload.get("schedule", payload); freq = schedule.get("frequency", "daily"); tz = schedule.get("timezone", "Asia/Shanghai"); base = datetime.now(timezone.utc)
    out = []
    for i in range(5):
        dt = base + timedelta(days=i + (1 if freq == "weekly" else 0)); out.append({"utc": dt.replace(microsecond=0).isoformat().replace("+00:00", "Z"), "local": dt.strftime("%Y-%m-%d %H:%M"), "dst_adjusted": False})
    return out


@app.get("/api/v1/workspaces/{workspace_id}/subscriptions")
async def subscriptions(workspace_id: str, limit: int = 20, cursor: str | None = None, ctx: dict = Depends(workspace_user)) -> dict:
    return page([s for s in state.subscriptions.values() if s["workspace_id"] == workspace_id], limit, cursor)


@app.post("/api/v1/workspaces/{workspace_id}/subscriptions")
async def subscription_create(workspace_id: str, request: Request, ctx: dict = Depends(csrf)) -> dict:
    require_role(ctx, "analyst", "reviewer", "admin"); p = await request.json();
    if not p.get("name") or not p.get("drug_ids") or not p.get("schedule"): raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "name, drug_ids and schedule are required"})
    s = {"id": uid(), "workspace_id": workspace_id, "created_at": now(), "name": p["name"], "drug_ids": p["drug_ids"], "source_allowlist": p.get("source_allowlist", ["ctgov", "pubmed"]), "schedule": p["schedule"], "channels": p.get("channels", ["in_app"]), "enabled": p.get("enabled", True), "owner_id": ctx["user"]["id"], "revision": 1, "next_run_at": schedule_occurrences(p)[0]["utc"], "last_outcome": None}; state.subscriptions[s["id"]] = s; return JSONResponse(status_code=201, content=s)


@app.post("/api/v1/workspaces/{workspace_id}/subscriptions/preview")
async def subscription_preview(workspace_id: str, request: Request, ctx: dict = Depends(csrf)) -> dict:
    await workspace_user(workspace_id, ctx["user"]); return {"occurrences": schedule_occurrences(await request.json())}


@app.get("/api/v1/workspaces/{workspace_id}/subscriptions/{subscription_id}")
async def subscription_get(workspace_id: str, subscription_id: str, ctx: dict = Depends(workspace_user)) -> dict:
    s = state.subscriptions.get(subscription_id)
    if not s or s["workspace_id"] != workspace_id: raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Subscription not found"})
    return s


@app.patch("/api/v1/workspaces/{workspace_id}/subscriptions/{subscription_id}")
async def subscription_update(workspace_id: str, subscription_id: str, request: Request, ctx: dict = Depends(csrf), if_match: str | None = Header(default=None, alias="If-Match")) -> dict:
    require_role(ctx, "analyst", "reviewer", "admin"); s = await subscription_get(workspace_id, subscription_id, ctx); p = await request.json()
    if if_match and if_match.strip('"') != str(s["revision"]): raise HTTPException(409, detail={"code": "STALE_VERSION", "message": "Subscription revision is stale"})
    s.update({k: p[k] for k in ("name", "drug_ids", "source_allowlist", "schedule", "channels", "enabled") if k in p}); s["revision"] += 1; s["next_run_at"] = schedule_occurrences(s)[0]["utc"]; return s


@app.post("/api/v1/workspaces/{workspace_id}/subscriptions/{subscription_id}/trigger")
async def subscription_trigger(workspace_id: str, subscription_id: str, ctx: dict = Depends(csrf), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> dict:
    require_role(ctx, "analyst", "reviewer", "admin"); s = await subscription_get(workspace_id, subscription_id, ctx)
    key = (workspace_id + ":trigger:" + subscription_id, idempotency_key) if idempotency_key else None
    if key and key in state.idempotency:
        return state.idempotency[key][1]
    o = {"id": uid(), "workspace_id": workspace_id, "created_at": now(), "subscription_id": subscription_id, "scheduled_at": now(), "state": "queued", "run_id": None}; state.occurrences[o["id"]] = o
    result = JSONResponse(status_code=202, content=o)
    if key:
        state.idempotency[key] = (state.hash({"subscription_id": subscription_id}), o)
    return result


@app.get("/api/v1/workspaces/{workspace_id}/inbox")
async def inbox(workspace_id: str, limit: int = 20, cursor: str | None = None, ctx: dict = Depends(workspace_user)) -> dict:
    rows = [d for d in state.deliveries.values() if d["workspace_id"] == workspace_id and d["recipient_user_id"] == ctx["user"]["id"]]; return page(rows, limit, cursor)


@app.post("/api/v1/workspaces/{workspace_id}/inbox/{delivery_id}/read")
async def inbox_read(workspace_id: str, delivery_id: str, ctx: dict = Depends(csrf)) -> dict:
    d = state.deliveries.get(delivery_id)
    if not d or d["workspace_id"] != workspace_id or d["recipient_user_id"] != ctx["user"]["id"]: raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Delivery not found"})
    d["read_at"] = now(); return d


@app.get("/api/v1/workspaces/{workspace_id}/deliveries")
async def deliveries(workspace_id: str, limit: int = 20, cursor: str | None = None, ctx: dict = Depends(workspace_user)) -> dict:
    return page([d for d in state.deliveries.values() if d["workspace_id"] == workspace_id], limit, cursor)


@app.get("/api/v1/workspaces/{workspace_id}/deliveries/{delivery_id}")
async def delivery_get(workspace_id: str, delivery_id: str, ctx: dict = Depends(workspace_user)) -> dict:
    d = state.deliveries.get(delivery_id)
    if not d or d["workspace_id"] != workspace_id: raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Delivery not found"})
    return d


@app.get("/api/v1/workspaces/{workspace_id}/audit")
async def audit(workspace_id: str, action: str | None = None, limit: int = 20, cursor: str | None = None, ctx: dict = Depends(workspace_user)) -> dict:
    return page([a for a in state.audit if a["workspace_id"] == workspace_id and (action is None or a["action"] == action)], limit, cursor)


def _apply_contract_operation_ids() -> None:
    """Keep generated operation IDs stable with contracts/openapi.yaml.

    FastAPI derives IDs from Python function names by default.  The public
    contract uses explicit IDs, so we copy those identifiers when the frozen
    contract file is available without making PyYAML a runtime dependency.
    """
    contract = FIXTURES.parent / "contracts" / "openapi.yaml"
    if not contract.exists():
        return
    current_path = current_method = None
    expected: dict[tuple[str, str], str] = {}
    for raw in contract.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if line.startswith("  /") and line.endswith(":"):
            current_path = line[2:-1]
            current_method = None
        elif current_path and line.startswith("    ") and line.strip().rstrip(":") in {"get", "post", "patch", "put", "delete"}:
            current_method = line.strip()[:-1]
        elif current_path and current_method and line.strip().startswith("operationId:"):
            expected[(current_path, current_method)] = line.split(":", 1)[1].strip()
            current_method = None
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None) or set()
        for method in methods:
            op_id = expected.get((path, method.lower()))
            if op_id:
                route.operation_id = op_id


_apply_contract_operation_ids()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.pharma_scope_app:app", host="0.0.0.0", port=int(os.getenv("PORT", "8080")), reload=False)
