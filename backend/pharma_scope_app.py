"""PharmaScope Lite authenticated API.

Live requests use a transactional PostgreSQL row repository; the independent
worker owns external source/model calls. Explicit replay supports fictional
fixtures for demonstrations without implicit live fallback.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import ipaddress
import json
import os
import re
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Iterable, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, PlainTextResponse
from pydantic import BaseModel, Field

from .repository import RepositoryUnavailable, RepositoryConflict, repository_from_env, restore_state, state_payload
from .auth import hash_password, verify_password
from sqlalchemy.exc import SQLAlchemyError
from .sources import ClinicalTrialsGovAdapter, PubMedAdapter, SourceError, SourceQuery, SourcePage
from .source_ingest import SnapshotIngestor
from .research import ResearchBudget, ResearchConfigurationError, ResearchContext, execute_live_research
from .gptr_adapter import GPTResearcherError, PharmaResearchConductor as GPTRConductor, ResearchBudget as GPTRBudget


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "docs" / "reference" / "PharmaScope_Lite_v1.0" / "fixtures"
DEFAULT_WORKSPACE = "dee59b72-2cb2-5255-934c-b44a3fd8911c"
SECOND_WORKSPACE = "b9c9d1b4-62c5-5b58-92d1-de56235db31d"
DEFAULT_USER = "dacd1189-f315-5985-98ae-dce1a533104c"
REVIEWER_USER = "830a0c39-02ed-53a8-9616-c4d7827fb9ad"
ADMIN_USER = "95023655-2f60-587d-834b-eabaa2e759af"
DUMMY_PASSWORD_HASH = hash_password("no-such-account-password")


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
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class DemoAccountRequest(BaseModel):
    user_id: str | None


class CreateMemberRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=12, max_length=256)
    role: str = Field(default="reader")


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class PasswordResetRequest(BaseModel):
    new_password: str = Field(min_length=12, max_length=256)


class DomainState:
    """Request/worker unit of work; persisted through the row repository."""

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
        # Local request throttles are deliberately transient. The reverse proxy
        # also limits public authentication routes across API workers.
        self.auth_attempts: dict[str, list[float]] = {}
        self.sources: dict[str, dict] = {
            "ctgov": {"source": "ctgov", "enabled": True, "configured": True, "state": "healthy", "last_success_at": None, "last_error_code": None, "coverage": {"records": 0}},
            "pubmed": {"source": "pubmed", "enabled": True, "configured": True, "state": "healthy", "last_success_at": None, "last_error_code": None, "coverage": {"records": 0}},
        }
        # Fixtures are business data only in explicit replay/demo mode.  Live
        # starts empty and is populated by migrations/seed-admin plus source
        # sync; it can never silently fall back to demo records.
        if os.getenv("PHARMA_RUNTIME_MODE", "live") in ("replay", "demo"):
            self.seed()

    def seed(self) -> None:
        ident = read_fixture("00-identities.json", {})
        ws = ident.get("workspace", {"id": DEFAULT_WORKSPACE, "name": "PharmaScope 演示研究组", "timezone": "Asia/Shanghai"})
        ws2 = ident.get("second_workspace", {"id": SECOND_WORKSPACE, "name": "隔离测试组", "timezone": "America/Los_Angeles"})
        self.workspaces[ws["id"]] = {**ws, "created_at": now()}
        self.workspaces[ws["id"]].update({"demo_user_id": DEFAULT_USER, "public_demo": True})
        self.workspaces[ws2["id"]] = {**ws2, "created_at": now()}
        for u in ident.get("users", []):
            self.users[u["id"]] = {**u, "is_active": True, "created_at": now()}
            self.memberships[(DEFAULT_WORKSPACE, u["id"])] = {"workspace_id": DEFAULT_WORKSPACE, "user_id": u["id"], "role": u.get("role", "analyst"), "enabled": True, "created_at": now()}
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
# Replay is intentionally in-memory.  Live/GPT mode selects a transactional
# PostgreSQL checkpoint repository when PHARMA_DATABASE_URL is configured; an
# unavailable repository is surfaced by /readyz instead of silently falling
# back to fixtures.
state_store = None
persistence_error: str | None = None
try:
    state_store = repository_from_env()
    if state_store:
        checkpoint = state_store.load()
        if checkpoint:
            restore_state(state, checkpoint)
except (RepositoryUnavailable, SQLAlchemyError) as exc:
    persistence_error = "Database unavailable or migrations required; check PHARMA_DATABASE_URL and run alembic upgrade head"


def error(code: str, message: str, status: int = 400, details: dict | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "details": details or {}, "request_id": uid()}})


def session_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def session_for(request: Request) -> dict | None:
    token = request.cookies.get("pharmascope_session")
    return state.sessions.get(session_key(token)) if token else None


def guest_subject(session: dict) -> tuple[dict, dict] | None:
    workspace_id = session.get("workspace_id")
    user_id = session.get("user_id")
    ws = state.workspaces.get(workspace_id)
    user = state.users.get(user_id)
    m = state.memberships.get((workspace_id, user_id))
    if not (ws and is_public_demo_workspace(ws) and selected_demo_user_id(ws) == user_id
            and user and user.get("is_active", True)
            and m and m.get("enabled", True)):
        return None
    return user, m


def selected_demo_user_id(workspace: dict) -> str | None:
    if "demo_user_id" in workspace:
        return workspace["demo_user_id"]
    # Older replay databases were seeded before the setting existed. Only the
    # known fictional replay workspace receives this compatibility default.
    if (os.getenv("PHARMA_RUNTIME_MODE", "live") in ("replay", "demo")
            and workspace.get("id") == DEFAULT_WORKSPACE):
        return DEFAULT_USER
    return None


def is_public_demo_workspace(workspace: dict, workspaces: dict | None = None) -> bool:
    workspaces = state.workspaces if workspaces is None else workspaces
    if any("public_demo" in candidate for candidate in workspaces.values()):
        return workspace.get("public_demo") is True
    return (os.getenv("PHARMA_RUNTIME_MODE", "live") in ("replay", "demo")
            and workspace.get("id") == DEFAULT_WORKSPACE)


def guest_session_valid_in_payload(token: str | None, payload: dict, *, guest_id: str,
                                   workspace_id: str, subject_user_id: str) -> bool:
    """Revalidate an open guest stream against a freshly loaded repository state."""
    if not token:
        return False
    session = payload.get("sessions", {}).get(session_key(token), {})
    if (not session.get("guest") or session.get("guest_id") != guest_id
            or session.get("workspace_id") != workspace_id
            or session.get("user_id") != subject_user_id
            or session.get("expires_at", 0) <= datetime.now(timezone.utc).timestamp()):
        return False
    workspaces = payload.get("workspaces", {})
    workspace = workspaces.get(workspace_id)
    user = payload.get("users", {}).get(subject_user_id)
    member = payload.get("memberships", {}).get(workspace_id + "|" + subject_user_id)
    return bool(workspace and is_public_demo_workspace(workspace, workspaces)
                and selected_demo_user_id(workspace) == subject_user_id
                and user and user.get("is_active", True)
                and member and member.get("enabled", True))


async def user_context(request: Request) -> dict:
    session = session_for(request)
    if not session:
        # This development-only escape hatch is opt-in and unavailable live.
        header_user = request.headers.get("X-User-Id") if os.getenv("PHARMA_ALLOW_DEV_HEADER", "0") == "1" else None
        if os.getenv("PHARMA_RUNTIME_MODE", "live") in ("replay", "demo") and header_user and header_user in state.users:
            return state.users[header_user]
        raise HTTPException(401, detail={"code": "AUTH_REQUIRED", "message": "Authentication required"})
    if session["expires_at"] < datetime.now(timezone.utc).timestamp():
        raise HTTPException(401, detail={"code": "AUTH_REQUIRED", "message": "Session expired"})
    if session.get("guest"):
        if not guest_subject(session):
            raise HTTPException(401, detail={"code": "AUTH_REQUIRED", "message": "Demo account is unavailable"})
        return {"id": session["guest_id"], "email": f"guest-{session['guest_id']}@pharmascope.invalid", "display_name": "游客", "is_active": True,
                "is_guest": True, "demo_user_id": session["user_id"], "guest_workspace_id": session["workspace_id"]}
    user = state.users.get(session["user_id"])
    if not user or not user.get("is_active", True) or not any(
        m.get("user_id") == user["id"] and m.get("enabled", True) for m in state.memberships.values()
    ):
        raise HTTPException(401, detail={"code": "AUTH_REQUIRED", "message": "Inactive account"})
    return user


def membership(workspace_id: str, user: dict) -> dict | None:
    m = state.memberships.get((workspace_id, user["id"]))
    return m if m and m.get("enabled", True) else None


def membership_contract(m: dict) -> dict:
    ws = state.workspaces.get(m.get("workspace_id"), {})
    return {"workspace_id": m.get("workspace_id"), "workspace_name": ws.get("name", ""), "role": m.get("role")}


def user_contract(user: dict) -> dict:
    return {"id": user.get("id"), "email": user.get("email"), "display_name": user.get("display_name"),
            "is_active": user.get("is_active", True), "is_guest": user.get("is_guest", False)}


async def workspace_user(workspace_id: str, user: dict = Depends(user_context)) -> dict:
    if workspace_id not in state.workspaces:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Workspace not found"})
    if user.get("is_guest"):
        if workspace_id != user.get("guest_workspace_id"):
            raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Workspace not found"})
        source = state.memberships.get((workspace_id, user["demo_user_id"]))
        if not source or not source.get("enabled", True):
            raise HTTPException(401, detail={"code": "AUTH_REQUIRED", "message": "Demo account is unavailable"})
        m = {**source, "role": "reader", "user_id": user["id"]}
        return {"user": user, "membership": m, "workspace_id": workspace_id,
                "subject_user_id": user["demo_user_id"], "is_guest": True}
    m = membership(workspace_id, user)
    if not m:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Workspace not found"})
    return {"user": user, "membership": m, "workspace_id": workspace_id,
            "subject_user_id": user["id"], "is_guest": False}


def require_role(ctx: dict, *roles: str) -> None:
    if ctx["membership"]["role"] not in roles:
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "Insufficient role"})


async def csrf(request: Request, ctx: dict = Depends(workspace_user)) -> dict:
    if ctx["is_guest"]:
        raise HTTPException(403, detail={"code": "GUEST_READ_ONLY", "message": "Guest access is read only"})
    token = request.headers.get("X-CSRF-Token")
    session = session_for(request)
    if session and (not token or not secrets.compare_digest(token, session.get("csrf", ""))):
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
    global persistence_error
    request_id = uid()
    request.state.request_id = request_id
    # A short database transaction covers authorization, mutation, audit and
    # idempotency together. External work runs only in the independent worker.
    async with state.lock:
        before = copy.deepcopy(state_payload(state))
        try:
            session = session_for(request)
            if (session and session.get("guest") and request.method not in ("GET", "HEAD", "OPTIONS")
                    and request.url.path.startswith("/api/v1/")
                    and request.url.path not in ("/api/v1/auth/login", "/api/v1/auth/guest-login", "/api/v1/auth/logout")):
                denied = error("GUEST_READ_ONLY", "Guest access is read only", 403)
                denied.headers["X-Request-Id"] = request_id
                return denied
            if state_store is None:
                if persistence_error and request.url.path not in ("/healthz", "/readyz"):
                    return error("DATABASE_UNAVAILABLE", persistence_error, 503)
                response = await call_next(request)
                if response.status_code < 400: record_audit(request, response.status_code)
                else: restore_state(state, before)
            else:
                with state_store.transaction():
                    current = state_store.load()
                    if current: restore_state(state, current)
                    persistence_error = None
                    before = copy.deepcopy(state_payload(state))
                    response = await call_next(request)
                    if response.status_code < 400:
                        record_audit(request, response.status_code)
                        after = state_payload(state)
                        if after != before:
                            state_store.save(after)
                        persistence_error = None
                    else: restore_state(state, before)
        except RepositoryConflict:
            restore_state(state, before)
            return error("CONCURRENT_UPDATE", "Refresh and retry this operation", 409)
        except SQLAlchemyError:
            restore_state(state, before)
            persistence_error = "Database transaction failed; no success was committed"
            return error("DATABASE_UNAVAILABLE", persistence_error, 503)
        except (ValueError, TypeError, KeyError):
            restore_state(state, before)
            return error("VALIDATION_ERROR", "Invalid request fields or JSON body", 422)
    response.headers["X-Request-Id"] = request_id
    return response


def record_audit(request: Request, status_code: int) -> None:
    if request.method not in ("POST", "PATCH", "DELETE", "PUT"): return
    parts = request.url.path.split("/")
    if "workspaces" not in parts: return
    ws = parts[parts.index("workspaces") + 1]
    session = session_for(request) or {}
    actor = session.get("user_id") or request.headers.get("X-User-Id")
    state.audit.append({"id": uid(), "workspace_id": ws, "actor_user_id": actor,
        "action": request.method.lower() + ":" + "/".join(parts[5:]),
        "resource_type": parts[5] if len(parts)>5 else "workspace",
        "request_id": request.state.request_id, "created_at": now(), "result": status_code})


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
    response = error("VALIDATION_ERROR", "Request validation failed", 422, {"fields": [{"loc":e["loc"],"type":e["type"],"msg":e["msg"]} for e in exc.errors()]})
    payload = json.loads(response.body)
    payload["error"]["request_id"] = getattr(request.state, "request_id", uid())
    response.body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    response.headers["content-length"] = str(len(response.body))
    return response


@app.get("/healthz")
async def healthz() -> dict:
    runtime = os.getenv("PHARMA_RUNTIME_MODE", "live").lower()
    return {"message": "ok", "status": "ok", "mode": "demo" if runtime in ("replay", "demo") else "live", "runtime_mode": runtime}


@app.get("/readyz")
async def readyz() -> dict:
    mode = os.getenv("PHARMA_RUNTIME_MODE", os.getenv("PHARMA_MODE", "live"))
    if persistence_error:
        return JSONResponse(status_code=503, content={"message": "database unavailable", "status": "not_ready", "database": "error", "error": persistence_error})
    if mode in {"live", "gptr"} and state_store is None:
        return JSONResponse(status_code=503, content={"message": "database is not configured", "status": "not_ready", "database": "missing"})
    return {"message": "ready", "status": "ready", "database": "postgresql" if state_store else "replay"}


def auth_limit(key: str, *, count: bool, maximum: int, window: int) -> None:
    stamp = time.monotonic()
    attempts = [value for value in state.auth_attempts.get(key, []) if value > stamp - window]
    if len(attempts) >= maximum:
        raise HTTPException(429, detail={"code": "RATE_LIMITED", "message": "Too many sign-in attempts; try again later"})
    if count:
        attempts.append(stamp)
    if attempts:
        state.auth_attempts[key] = attempts
    else:
        state.auth_attempts.pop(key, None)
    if len(state.auth_attempts) > 4096:
        state.auth_attempts = {key: values for key, values in state.auth_attempts.items()
                               if values and values[-1] > stamp - 900}


def auth_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    if peer in ("127.0.0.1", "::1"):
        forwarded = request.headers.get("X-Real-IP", "")
        try:
            return str(ipaddress.ip_address(forwarded))
        except ValueError:
            pass
    return peer


def prune_sessions() -> None:
    stamp = datetime.now(timezone.utc).timestamp()
    for key, session in list(state.sessions.items()):
        if (not re.fullmatch(r"[0-9a-f]{64}", key) or session.get("expires_at", 0) < stamp
                or (session.get("guest") and not guest_subject(session))):
            state.sessions.pop(key, None)


def issue_session(request: Request, response: Response, *, user_id: str,
                  guest: bool = False, workspace_id: str | None = None) -> tuple[dict, str]:
    prune_sessions()
    previous = request.cookies.get("pharmascope_session")
    if previous:
        state.sessions.pop(session_key(previous), None)
    active = [(key, value) for key, value in state.sessions.items() if value.get("user_id") == user_id and value.get("guest") == guest]
    maximum = 500 if guest else 10
    if guest and sum(bool(value.get("guest")) for value in state.sessions.values()) >= 1000:
        raise HTTPException(429, detail={"code": "RATE_LIMITED", "message": "Guest capacity reached; try again later"})
    if len(active) >= maximum:
        oldest = sorted(active, key=lambda item: item[1].get("created_at", 0))[:len(active) - maximum + 1]
        for key, _ in oldest:
            state.sessions.pop(key, None)
    token, csrf_token = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
    lifetime = 3600 if guest else 43200
    session = {"user_id": user_id, "csrf": csrf_token, "created_at": datetime.now(timezone.utc).timestamp(),
               "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=lifetime)).timestamp()}
    if guest:
        session.update({"guest": True, "guest_id": uid(), "workspace_id": workspace_id})
    state.sessions[session_key(token)] = session
    response.set_cookie("pharmascope_session", token, httponly=True, samesite="lax",
                        secure=os.getenv("PHARMA_COOKIE_SECURE", "0" if os.getenv("PHARMA_RUNTIME_MODE") in ("replay", "demo") else "1") == "1",
                        max_age=lifetime, path="/")
    return session, csrf_token


def auth_contract(user: dict, memberships: list[dict], csrf_token: str) -> dict:
    return {"runtime_mode": os.getenv("PHARMA_RUNTIME_MODE", "live"), "user": user_contract(user),
            "memberships": memberships, "csrf_token": csrf_token, "is_guest": user.get("is_guest", False)}


@app.post("/api/v1/auth/login")
async def login(body: LoginRequest, request: Request, response: Response) -> dict:
    email = body.email.strip().lower()
    ip = auth_ip(request)
    pair_key, ip_key = f"password:{ip}:{email}", f"password-ip:{ip}"
    auth_limit(pair_key, count=False, maximum=5, window=900)
    auth_limit(ip_key, count=False, maximum=30, window=900)
    user = next((u for u in state.users.values() if u.get("email", "").lower() == email), None)
    allowed = os.getenv("PHARMA_DEMO_PASSWORD", "demo")
    valid = verify_password(body.password, user.get("password_hash") or DUMMY_PASSWORD_HASH) if user else verify_password(body.password, DUMMY_PASSWORD_HASH)
    if os.getenv("PHARMA_RUNTIME_MODE", "live") in ("replay", "demo") and user and not user.get("password_hash"):
        valid = secrets.compare_digest(body.password, allowed)
    if (not user or not user.get("is_active", True) or not valid
            or not any(m.get("user_id") == user["id"] and m.get("enabled", True) for m in state.memberships.values())):
        auth_limit(pair_key, count=True, maximum=5, window=900)
        auth_limit(ip_key, count=True, maximum=30, window=900)
        raise HTTPException(401, detail={"code": "AUTH_REQUIRED", "message": "Invalid credentials"})
    state.auth_attempts.pop(pair_key, None)
    session, csrf_token = issue_session(request, response, user_id=user["id"])
    return auth_contract(user, [membership_contract(m) for m in state.memberships.values()
                                if m["user_id"] == user["id"] and m["workspace_id"] != "demo-workspace" and m.get("enabled", True)], csrf_token)


@app.post("/api/v1/auth/guest-login")
async def guest_login(request: Request, response: Response) -> dict:
    auth_limit(f"guest:{auth_ip(request)}", count=True, maximum=30, window=60)
    configured = []
    for workspace in state.workspaces.values():
        user_id = selected_demo_user_id(workspace)
        if user_id and is_public_demo_workspace(workspace) and guest_subject({"workspace_id": workspace["id"], "user_id": user_id}):
            configured.append((workspace, user_id))
    if not configured:
        raise HTTPException(503, detail={"code": "DEMO_UNAVAILABLE", "message": "Demo account is not configured or available"})
    workspace, user_id = sorted(configured, key=lambda item: item[0]["id"])[0]
    session, csrf_token = issue_session(request, response, user_id=user_id, guest=True, workspace_id=workspace["id"])
    guest = {"id": session["guest_id"], "email": f"guest-{session['guest_id']}@pharmascope.invalid",
             "display_name": "游客", "is_active": True, "is_guest": True}
    return auth_contract(guest, [{"workspace_id": workspace["id"], "workspace_name": workspace.get("name", ""), "role": "reader"}], csrf_token)


@app.post("/api/v1/auth/logout")
async def logout(request: Request, response: Response, csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"), _user: dict = Depends(user_context)) -> dict:
    token = request.cookies.get("pharmascope_session")
    session = session_for(request)
    if token and (not csrf_token or not session or not secrets.compare_digest(csrf_token, session.get("csrf", ""))):
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "CSRF token required"})
    if token:
        state.sessions.pop(session_key(token), None)
    response.delete_cookie("pharmascope_session", path="/")
    return {"message": "logged out"}


@app.get("/api/v1/auth/me")
async def me(request: Request, user: dict = Depends(user_context)) -> dict:
    session = session_for(request)
    csrf_token = session.get("csrf") if session else None
    if user.get("is_guest"):
        workspace = state.workspaces[user["guest_workspace_id"]]
        memberships = [{"workspace_id": workspace["id"], "workspace_name": workspace.get("name", ""), "role": "reader"}]
    else:
        memberships = [membership_contract(m) for m in state.memberships.values() if m["user_id"] == user["id"] and m["workspace_id"] != "demo-workspace" and m.get("enabled", True)]
    return auth_contract(user, memberships, csrf_token)


def revoke_sessions_for_user(user_id: str, *, except_key: str | None = None,
                             guest_only: bool = False, workspace_id: str | None = None) -> None:
    for key, session in list(state.sessions.items()):
        if (key != except_key and session.get("user_id") == user_id
                and (not guest_only or session.get("guest"))
                and (workspace_id is None or session.get("workspace_id") == workspace_id)):
            state.sessions.pop(key, None)


def require_auth_csrf(request: Request) -> dict:
    session = session_for(request)
    token = request.headers.get("X-CSRF-Token")
    if not session or not token or not secrets.compare_digest(token, session.get("csrf", "")):
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "CSRF token required"})
    if session.get("guest"):
        raise HTTPException(403, detail={"code": "GUEST_READ_ONLY", "message": "Guest access is read only"})
    return session


@app.post("/api/v1/auth/password")
async def change_password(body: PasswordChangeRequest, request: Request,
                          user: dict = Depends(user_context)) -> dict:
    session = require_auth_csrf(request)
    attempt_key = f"password-change:{auth_ip(request)}:{user['id']}"
    auth_limit(attempt_key, count=False, maximum=5, window=900)
    encoded = user.get("password_hash", "")
    valid = verify_password(body.current_password, encoded)
    if not encoded and os.getenv("PHARMA_RUNTIME_MODE", "live") in ("replay", "demo"):
        valid = secrets.compare_digest(body.current_password, os.getenv("PHARMA_DEMO_PASSWORD", "demo"))
    if not valid:
        auth_limit(attempt_key, count=True, maximum=5, window=900)
        raise HTTPException(401, detail={"code": "AUTH_REQUIRED", "message": "Invalid credentials"})
    state.auth_attempts.pop(attempt_key, None)
    user["password_hash"] = hash_password(body.new_password)
    current = request.cookies.get("pharmascope_session")
    revoke_sessions_for_user(user["id"], except_key=session_key(current) if current else None)
    return {"message": "Password changed"}


def records_for(ws: str, kind: str | None = None) -> list[dict]:
    return [r for r in state.records.values() if r.get("workspace_id") == ws and (kind is None or r.get("kind") == kind)]


def with_projection(record: dict) -> dict:
    # Trial/Publication are source records with a nested projection in the
    # contract.  Keep that shape intact so generated OpenAPI clients can decode
    # either object without special casing the list and detail endpoints.
    p = copy.deepcopy(record)
    p.setdefault("current_projection", {})
    return p


def sources_for(workspace_id, *, persist=False):
    values={}
    replay=os.getenv("PHARMA_RUNTIME_MODE","live") in ("replay","demo")
    for source in ("ctgov","pubmed"):
        key=workspace_id+":"+source
        if key in state.sources:
            values[source]=state.sources[key]
        else:
            values[source]={"workspace_id":workspace_id,"source":source,"enabled":True,
                "configured":replay or source=="ctgov" or bool(os.getenv("NCBI_EMAIL")),
                "state":"healthy" if replay else "unknown","last_success_at":None,"last_error_code":None,"coverage":{"records":0}}
            if persist:
                state.sources[key]=values[source]
    return values


def source_health_payload(workspace_id) -> list[dict]:
    fields=("source","enabled","configured","state","last_success_at","last_error_code")
    return [{k:v.get(k) for k in fields} for v in sources_for(workspace_id).values()]


@app.get("/api/v1/workspaces/{workspace_id}/dashboard")
async def dashboard(workspace_id: str, ctx: dict = Depends(workspace_user)) -> dict:
    events = [e for e in state.events.values() if e.get("workspace_id") == workspace_id]
    pending = [r for r in state.reports.values() if r.get("workspace_id") == workspace_id and r.get("state") in ("in_review", "draft")]
    watched = {d for s in state.subscriptions.values() if s.get("workspace_id") == workspace_id and s.get("enabled") for d in s.get("drug_ids", [])}
    return {"watched_drugs": len(watched), "events_last_7_days": len(events), "pending_reviews": len(pending), "source_health": source_health_payload(workspace_id), "as_of": now(), "is_demo": os.getenv("PHARMA_RUNTIME_MODE", "live") == "replay"}


@app.get("/api/v1/workspaces/{workspace_id}/members")
async def members(workspace_id: str, limit: int = 20, cursor: str | None = None, ctx: dict = Depends(workspace_user)) -> dict:
    if ctx["is_guest"]:
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "Member directory is private"})
    allowed = None if ctx["membership"]["role"] == "admin" else ctx["user"]["id"]
    return page([{"user": user_contract(state.users.get(m["user_id"], {})), "role": m.get("role"), "enabled": m.get("enabled", True)}
                 for (ws, _), m in state.memberships.items() if ws == workspace_id and (allowed is None or m["user_id"] == allowed)], limit, cursor)


def valid_email(value: str) -> str:
    email = value.strip().lower()
    if not re.fullmatch(r"[^\s@]{1,64}@[^\s@]{1,255}\.[^\s@.]{2,}", email):
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "A valid email address is required"})
    return email


@app.post("/api/v1/workspaces/{workspace_id}/members")
async def member_create(workspace_id: str, body: CreateMemberRequest, ctx: dict = Depends(csrf)) -> JSONResponse:
    require_role(ctx, "admin")
    email = valid_email(body.email)
    if body.role not in ("reader", "analyst", "reviewer", "admin"):
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "Invalid role"})
    if any(u.get("email", "").lower() == email for u in state.users.values()):
        raise HTTPException(409, detail={"code": "ACCOUNT_EXISTS", "message": "Account already exists"})
    user_id = uid()
    user = {"id": user_id, "email": email, "display_name": body.display_name.strip(),
            "password_hash": hash_password(body.password), "is_active": True, "created_at": now()}
    if not user["display_name"]:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "Display name is required"})
    member = {"workspace_id": workspace_id, "user_id": user_id, "role": body.role,
              "enabled": True, "created_at": now()}
    state.users[user_id] = user
    state.memberships[(workspace_id, user_id)] = member
    return JSONResponse(status_code=201, content={"user": user_contract(user), "role": body.role, "enabled": True})


@app.patch("/api/v1/workspaces/{workspace_id}/members/{user_id}")
async def member_update(workspace_id: str, user_id: str, request: Request, ctx: dict = Depends(csrf)) -> dict:
    require_role(ctx, "admin")
    m = state.memberships.get((workspace_id, user_id))
    if not m:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Member not found"})
    payload = await request.json()
    if not isinstance(payload, dict) or not payload or set(payload) - {"role", "enabled"}:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "Only role and enabled can be changed"})
    if "role" in payload and payload["role"] not in ("reader", "analyst", "reviewer", "admin"):
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "Invalid role"})
    if "enabled" in payload and not isinstance(payload["enabled"], bool):
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "enabled must be a boolean"})
    new_role = payload.get("role", m.get("role"))
    new_enabled = payload.get("enabled", m.get("enabled", True))
    if m.get("role") == "admin" and m.get("enabled", True) and (new_role != "admin" or not new_enabled):
        other_admins = [other for (ws, uid), other in state.memberships.items()
                        if ws == workspace_id and uid != user_id and other.get("role") == "admin"
                        and other.get("enabled", True) and state.users.get(uid, {}).get("is_active", True)]
        if not other_admins:
            raise HTTPException(409, detail={"code": "LAST_ADMIN", "message": "At least one active administrator is required"})
    changed = new_role != m.get("role") or new_enabled != m.get("enabled", True)
    m["role"] = new_role
    if "enabled" in payload:
        m["enabled"] = payload["enabled"]
    if changed:
        revoke_sessions_for_user(user_id)
    return {**m, "user": user_contract(state.users.get(user_id, {}))}


@app.post("/api/v1/workspaces/{workspace_id}/members/{user_id}/password")
async def member_password_reset(workspace_id: str, user_id: str, body: PasswordResetRequest,
                                ctx: dict = Depends(csrf)) -> dict:
    require_role(ctx, "admin")
    member = state.memberships.get((workspace_id, user_id))
    user = state.users.get(user_id)
    if not member or not user:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Member not found"})
    # Passwords are global account credentials. A workspace administrator may
    # reset one only if they administer every workspace that account can enter.
    for (other_workspace, other_user), other_member in state.memberships.items():
        if other_user != user_id or not other_member.get("enabled", True):
            continue
        actor_member = state.memberships.get((other_workspace, ctx["user"]["id"]))
        if not actor_member or not actor_member.get("enabled", True) or actor_member.get("role") != "admin":
            raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "Account belongs to another workspace"})
    user["password_hash"] = hash_password(body.new_password)
    revoke_sessions_for_user(user_id)
    return {"message": "Password reset"}


def demo_account_contract(workspace_id: str) -> dict:
    selected = selected_demo_user_id(state.workspaces[workspace_id])
    user = state.users.get(selected) if selected else None
    member = state.memberships.get((workspace_id, selected)) if selected else None
    return {"user_id": selected, "user": user_contract(user) if user else None,
            "enabled": bool(is_public_demo_workspace(state.workspaces[workspace_id]) and user
                            and user.get("is_active", True) and member and member.get("enabled", True))}


@app.get("/api/v1/workspaces/{workspace_id}/settings/demo-account")
async def demo_account_get(workspace_id: str, ctx: dict = Depends(workspace_user)) -> dict:
    require_role(ctx, "admin")
    return demo_account_contract(workspace_id)


@app.patch("/api/v1/workspaces/{workspace_id}/settings/demo-account")
async def demo_account_set(workspace_id: str, body: DemoAccountRequest,
                           ctx: dict = Depends(csrf)) -> dict:
    require_role(ctx, "admin")
    if body.user_id is not None:
        user = state.users.get(body.user_id)
        member = state.memberships.get((workspace_id, body.user_id))
        if not user or not user.get("is_active", True) or not member or not member.get("enabled", True):
            raise HTTPException(422, detail={"code": "INVALID_DEMO_ACCOUNT", "message": "Select an active member of this workspace"})
    previous = selected_demo_user_id(state.workspaces[workspace_id])
    for workspace in state.workspaces.values():
        workspace["public_demo"] = workspace["id"] == workspace_id
    state.workspaces[workspace_id]["demo_user_id"] = body.user_id
    if previous != body.user_id or any(session.get("guest") and session.get("workspace_id") != workspace_id for session in state.sessions.values()):
        for key, session in list(state.sessions.items()):
            if session.get("guest"):
                state.sessions.pop(key, None)
    return demo_account_contract(workspace_id)


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
    return page([alias_contract(a) for a in state.aliases.values() if a["workspace_id"] == workspace_id and a["drug_id"] == drug_id], limit, cursor)


@app.post("/api/v1/workspaces/{workspace_id}/drugs/{drug_id}/aliases")
async def alias_create(workspace_id: str, drug_id: str, request: Request, ctx: dict = Depends(csrf)) -> dict:
    require_role(ctx, "analyst", "reviewer", "admin")
    get_drug(workspace_id, drug_id)
    p = await request.json()
    if p.get("evidence_id") and state.evidence.get(p["evidence_id"],{}).get("workspace_id")!=workspace_id:
        raise HTTPException(404,detail={"code":"NOT_FOUND","message":"Evidence not found"})
    if not p.get("alias") or not p.get("namespace") or not p.get("note"):
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "alias, namespace and note are required"})
    a = {"id": uid(), "workspace_id": workspace_id, "drug_id": drug_id, "alias": p["alias"], "normalized_alias": str(p["alias"]).strip().lower(), "namespace": p["namespace"], "status": "pending", "evidence_id": p.get("evidence_id"), "note": p.get("note", ""), "proposed_by": ctx["user"]["id"], "reviewed_by": None, "reviewed_at": None, "created_at": now()}
    state.aliases[a["id"]] = a
    return JSONResponse(status_code=201, content=alias_contract(a))


@app.get("/api/v1/workspaces/{workspace_id}/aliases")
async def alias_pending(workspace_id: str, status: str | None = None, limit: int = 20, cursor: str | None = None, ctx: dict = Depends(workspace_user)) -> dict:
    items = [alias_contract(a) for a in state.aliases.values() if a["workspace_id"] == workspace_id and (status is None or a["status"] == status)]
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
    return alias_contract(a)


def link_contract(value):
    return {k:value.get(k) for k in ("id","workspace_id","created_at","record_id","drug_id","relation","evidence_id","note","status")}


def alias_contract(value):
    return {k:value.get(k) for k in ("id","workspace_id","created_at","drug_id","alias","namespace","evidence_id","note","status","proposed_by","reviewed_by")}


def list_links(workspace_id: str, status: str | None = None) -> list[dict]:
    return [link_contract(x) for x in state.links.values() if x["workspace_id"] == workspace_id and (status is None or x["status"] == status)]


@app.get("/api/v1/workspaces/{workspace_id}/entity-links")
async def links_list(workspace_id: str, status: str | None = None, limit: int = 20, cursor: str | None = None, ctx: dict = Depends(workspace_user)) -> dict:
    return page(list_links(workspace_id, status), limit, cursor)


@app.post("/api/v1/workspaces/{workspace_id}/entity-links")
async def link_create(workspace_id: str, request: Request, ctx: dict = Depends(csrf)) -> dict:
    require_role(ctx, "analyst", "reviewer", "admin")
    p = await request.json()
    if p.get("evidence_id") and state.evidence.get(p["evidence_id"],{}).get("workspace_id")!=workspace_id:
        raise HTTPException(404,detail={"code":"NOT_FOUND","message":"Evidence not found"})
    if not p.get("record_id") or not p.get("drug_id") or not p.get("relation") or not p.get("note"):
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "record_id, drug_id, relation and note are required"})
    if state.records.get(p["record_id"], {}).get("workspace_id") != workspace_id or state.drugs.get(p["drug_id"], {}).get("workspace_id") != workspace_id:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Record or drug not found"})
    x = {"id": uid(), "workspace_id": workspace_id, "record_id": p["record_id"], "drug_id": p["drug_id"], "relation": p["relation"], "status": "pending", "evidence_id": p.get("evidence_id"), "note": p.get("note", ""), "proposed_by": ctx["user"]["id"], "reviewed_by": None, "reviewed_at": None, "created_at": now()}
    state.links[x["id"]] = x
    return JSONResponse(status_code=201, content=link_contract(x))


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
    return link_contract(x)


@app.get("/api/v1/workspaces/{workspace_id}/sources")
async def source_list(workspace_id: str, ctx: dict = Depends(workspace_user)) -> dict:
    return {"items": source_health_payload(workspace_id)}


@app.patch("/api/v1/workspaces/{workspace_id}/sources/{source}")
async def source_update(workspace_id: str, source: str, request: Request, ctx: dict = Depends(csrf)) -> dict:
    require_role(ctx, "admin")
    if source not in sources_for(workspace_id):
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Source not found"})
    p = await request.json()
    if not isinstance(p.get("enabled"), bool):
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "enabled is required"})
    sources_for(workspace_id, persist=True)[source].update({"enabled": p["enabled"]})
    return next(item for item in source_health_payload(workspace_id) if item["source"] == source)


@app.post("/api/v1/workspaces/{workspace_id}/sources/{source}/check")
async def source_check(workspace_id: str, source: str, ctx: dict=Depends(csrf)) -> dict:
    require_role(ctx,"admin")
    if source not in ("ctgov","pubmed"): raise HTTPException(404,detail={"code":"NOT_FOUND","message":"Source not found"})
    replay=os.getenv("PHARMA_RUNTIME_MODE","live") in ("replay","demo")
    job={"id":uid(),"workspace_id":workspace_id,"created_at":now(),"kind":"ingest","state":"completed" if replay else "queued",
        "created_by":ctx["user"]["id"],"payload":{"sources":[source],"health_check":True},"coverage":[{"source":source,"state":"complete","mode":"replay"}] if replay else [],"progress":{"processed":0,"total":None},"attempt":0}
    state.jobs[job["id"]]=job
    return JSONResponse(status_code=202,content=job_contract(job))


@app.post("/api/v1/workspaces/{workspace_id}/source-syncs")
async def source_sync(workspace_id: str, request: Request, ctx: dict = Depends(csrf), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> dict:
    require_role(ctx, "analyst", "reviewer", "admin")
    p = await request.json()
    if not isinstance(p.get("sources"), list) or not p["sources"] or not isinstance(p.get("drug_ids"), list) or not p["drug_ids"] or p.get("mode") not in ("discovery", "refresh_linked"):
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "sources, drug_ids and mode are required"})
    if not isinstance(p.get("sources"), list) or not p["sources"]:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "sources is required"})
    validate_scope(workspace_id, p["drug_ids"], p["sources"])
    requested_sources = p["sources"]
    source = requested_sources[0]
    if source not in sources_for(workspace_id):
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "Unsupported source"})
    key = (workspace_id + ":sync:" + ctx["user"]["id"], idempotency_key or uid())
    if key in state.idempotency:
        if state.idempotency[key][0] != state.hash(p):
            raise HTTPException(409, detail={"code": "IDEMPOTENCY_CONFLICT", "message": "Idempotency key was already used with a different request"})
        return job_contract(state.idempotency[key][1])
    j = {"id": uid(), "workspace_id": workspace_id, "created_at": now(), "kind": "ingest", "state": "queued", "created_by":ctx["user"]["id"], "payload": p, "progress": {"processed": 0, "total": None}, "coverage": [], "attempt": 0, "error_code": None}
    state.jobs[j["id"]] = j
    state.idempotency[key] = (state.hash(p), j)
    if os.getenv("PHARMA_RUNTIME_MODE", "live") in ("replay", "demo"):
        coverage = []
        for source_name in requested_sources:
            key_name = "ctgov" if source_name in ("ctgov", "clinicaltrials_gov") else source_name
            count = len(records_for(workspace_id, "trial" if key_name == "ctgov" else "publication")) if key_name in ("ctgov", "pubmed") else 0
            coverage.append({"source": key_name, "state": "complete", "records": count, "mode": "replay"})
        j.update({"state": "completed", "coverage": coverage, "progress": {"processed": sum(x["records"] for x in coverage), "total": sum(x["records"] for x in coverage)}, "finished_at": now()})
    return JSONResponse(status_code=202, content=job_contract(j))


async def _execute_source_sync(job_id: str, request_payload: dict[str, Any]) -> None:
    """Run a real source sync and persist observations/snapshots.

    Each source has its own outcome.  A failed source leaves an explicit failed
    job and coverage entry; it is never represented as an empty successful page.
    """
    job = state.jobs.get(job_id)
    if not job:
        return
    ws = job["workspace_id"]
    job.update({"state": "running", "attempt": int(job.get("attempt", 0)) + 1, "started_at": now(), "updated_at": now()})
    checkpoint()
    if job.get("created_by") and not execution_authorized(ws,job["created_by"]):
        job.update(state="failed",error_code="OWNER_PERMISSION_REVOKED",finished_at=now())
        checkpoint();return
    ingestor = SnapshotIngestor(state)
    coverage: list[dict[str, Any]] = []
    source_names = list(dict.fromkeys(request_payload.get("sources", [])))
    drugs = [state.drugs.get(d) for d in request_payload.get("drug_ids", [])]
    query_text = " OR ".join(str(d.get("display_name") or d.get("development_code")) for d in drugs if d)
    query_text = query_text or str(request_payload.get("query") or "")
    for source_name in source_names:
        if source_name not in ("ctgov", "clinicaltrials_gov", "pubmed"):
            coverage.append({"source": source_name, "state": "failed", "error_code": "unsupported_source"})
            continue
        adapter = None
        try:
            if not sources_for(ws).get(source_name,{}).get("enabled"):
                raise SourceError("disabled","Source is disabled")
            adapter = ClinicalTrialsGovAdapter() if source_name in ("ctgov", "clinicaltrials_gov") else PubMedAdapter()
            if request_payload.get("health_check"):
                result=await adapter.health()
                sources_for(ws, persist=True)[source_name].update(result)
                coverage.append({"source":source_name,"state":"complete" if result["state"]=="healthy" else "failed","error_code":result.get("last_error_code"),"records":0})
                continue
            if request_payload.get("mode")=="refresh_linked":
                linked_ids={x["record_id"] for x in state.links.values() if x.get("workspace_id")==ws and x.get("drug_id") in request_payload["drug_ids"] and x.get("status")=="approved"}
                linked=[r for r in state.records.values() if r.get("workspace_id")==ws and r.get("id") in linked_ids and r.get("source")==source_name]
                if not linked: raise SourceError("NO_APPROVED_LINKS","Confirm drug/source record links before refreshing or subscribing")
                items=[]; failures=[]
                for record in linked[:100]:
                    try:
                        envelope=await adapter.fetch(record["external_id"])
                        ingestor.ingest(ws,envelope,operation_key=f"{job_id}:{envelope.source}:{envelope.external_id}")
                        items.append(envelope)
                    except SourceError as exc:
                        ingestor.record_failure(ws,source=source_name,external_id=record["external_id"],operation_key=job_id+record["id"],error=exc)
                        failures.append(exc.code)
                    checkpoint()
                page_result=SourcePage(source=source_name,items=items,next_cursor=None,coverage={"errors":failures,"truncated":len(linked)>100})
            else:
                page_result = await adapter.search(SourceQuery(query=query_text, limit=min(int(request_payload.get("limit", 100)), 100),cursor=request_payload.get("cursor")))
            processed = 0
            for envelope in page_result.items:
                observation=ingestor.ingest(ws, envelope, operation_key=f"{job_id}:{envelope.source}:{envelope.external_id}")
                for drug in drugs:
                    if drug and drug.get("workspace_id")==ws and not any(x.get("workspace_id")==ws and x.get("record_id")==observation["record_id"] and x.get("drug_id")==drug["id"] for x in state.links.values()):
                        link_id=uid()
                        state.links[link_id]={"id":link_id,"workspace_id":ws,"record_id":observation["record_id"],"drug_id":drug["id"],"relation":"unspecified","evidence_id":None,"status":"pending","note":"Source search match requires human confirmation","created_at":now()}
                processed += 1
                job["progress"]={"processed":processed,"total":None}
                checkpoint()
            failures=page_result.coverage.get("errors",[])
            truncated=bool(page_result.next_cursor) or bool(page_result.coverage.get("truncated"))
            health=sources_for(ws, persist=True)[source_name]
            health.update(state="degraded" if failures and processed else "unavailable" if failures else "healthy",configured=True,last_error_code=failures[0] if failures else None,coverage={"records":processed})
            if processed or not failures: health["last_success_at"]=now()
            coverage.append({"source":source_name,"state":"failed" if failures and not processed else "partial" if failures or truncated else "complete", "records":processed,"truncated":truncated,"next_cursor":page_result.next_cursor,"error_code":failures[0] if failures else None,"limitations":failures})
        except SourceError as exc:
            source_key = "ctgov" if source_name in ("ctgov", "clinicaltrials_gov") else source_name
            if source_key in sources_for(ws):
                sources_for(ws, persist=True)[source_key].update({"state": "unavailable", "configured": exc.code != "configuration", "last_error_code": exc.code})
            coverage.append({"source": source_key, "state": "failed", "error_code": exc.code, "message": str(exc)})
        except Exception as exc:
            key_name = "ctgov" if source_name in ("ctgov", "clinicaltrials_gov") else source_name
            if key_name in sources_for(ws):
                sources_for(ws, persist=True)[key_name].update({"state": "unavailable", "last_error_code": "adapter_error"})
            coverage.append({"source": key_name, "state": "failed", "error_code": "adapter_error", "message": "Source adapter failed; check configuration and source status"})
        finally:
            if adapter is not None and hasattr(adapter, "aclose"):
                await adapter.aclose()  # type: ignore[attr-defined]
    failed = [x for x in coverage if x.get("state") == "failed"]
    job.update({"state": "failed" if failed and len(failed) == len(coverage) else ("partial" if failed or any(x.get("state")=="partial" for x in coverage) else "completed"), "coverage": coverage, "progress": {"processed": sum(int(x.get("records", 0)) for x in coverage), "total": None}, "error_code": failed[0].get("error_code") if failed else None, "finished_at": now()})
    checkpoint()


def coverage_contract(value):
    return {"source":value["source"],"status":value.get("status",value.get("state","partial")),
        "records_count":value.get("records_count",value.get("records",0)),"truncated":bool(value.get("truncated",False)),
        "as_of":value.get("as_of"),"limitations":value.get("limitations",[]) + ([value.get("error_code") or "Source failed",value.get("message") or "See source configuration"] if value.get("state")=="failed" else [])}


def job_contract(job):
    return {**{k:job.get(k) for k in ("id","workspace_id","created_at","kind","state","attempt","error_code","progress")},
        "coverage":[coverage_contract(c) for c in job.get("coverage",[])]}


@app.get("/api/v1/workspaces/{workspace_id}/jobs/{job_id}")
async def job_get(workspace_id: str, job_id: str, ctx: dict = Depends(workspace_user)) -> dict:
    j = state.jobs.get(job_id)
    if not j or j["workspace_id"] != workspace_id:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Job not found"})
    return job_contract(j)


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
        if os.getenv("PHARMA_RUNTIME_MODE","live") in ("replay","demo") and not linked and kind == "trial" and drug_id == "dd1dcb81-e4b6-5343-b4a6-544bf716d867":
            linked = {x["id"] for x in records_for(workspace_id, "trial")}
        rows = [x for x in rows if x["id"] in linked]
    return rows


@app.get("/api/v1/workspaces/{workspace_id}/trials")
async def trials(workspace_id: str, drug_id: str | None = None, query: str | None = None, status: str | None = None, has_results: bool | None = None, observed_since: str | None = None, limit: int = 20, cursor: str | None = None, ctx: dict = Depends(workspace_user)) -> dict:
    rows=project_filter(workspace_id,"trial",drug_id,query,status,has_results)
    if observed_since: rows=[r for r in rows if parse_time(r["updated_at"])>=parse_time(observed_since)]
    return page(rows,limit,cursor)


@app.get("/api/v1/workspaces/{workspace_id}/trials/{trial_id}")
async def trial(workspace_id: str, trial_id: str, ctx: dict = Depends(workspace_user)) -> dict:
    r = state.records.get(trial_id)
    if not r or r.get("workspace_id") != workspace_id or r.get("kind") != "trial":
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Trial not found"})
    return with_projection(r)


@app.get("/api/v1/workspaces/{workspace_id}/publications")
async def publications(workspace_id: str, drug_id: str | None = None, query: str | None = None, status: str | None = None, has_results: bool | None = None, observed_since: str | None = None, limit: int = 20, cursor: str | None = None, ctx: dict = Depends(workspace_user)) -> dict:
    rows=project_filter(workspace_id,"publication",drug_id,query,status,has_results)
    if observed_since: rows=[r for r in rows if parse_time(r["updated_at"])>=parse_time(observed_since)]
    return page(rows,limit,cursor)


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
    return page(sorted([{k:v for k,v in o.items() if k!="operation_key"} for o in state.observations.values() if o.get("workspace_id") == workspace_id and o.get("record_id") == record_id], key=lambda x: x.get("observation_seq", 0)), limit, cursor)


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
        if os.getenv("PHARMA_RUNTIME_MODE","live") in ("replay","demo") and not linked and drug_id == "dd1dcb81-e4b6-5343-b4a6-544bf716d867":
            linked = {r["id"] for r in records_for(workspace_id, "trial")}
        rows = [e for e in rows if e.get("record_id") in linked]
    if observed_since: rows=[r for r in rows if parse_time(r["updated_at"])>=parse_time(observed_since)]
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
    validate_scope(workspace_id, p["drug_ids"], p["source_allowlist"], p["time_range"])
    ResearchBudget.from_mapping(p.get("budget"))
    key = (workspace_id + ":run:" + ctx["user"]["id"], idempotency_key or uid())
    if key in state.idempotency:
        if state.idempotency[key][0] != state.hash(p):
            raise HTTPException(409, detail={"code": "IDEMPOTENCY_CONFLICT", "message": "Idempotency key was already used with a different request"})
        return state.idempotency[key][1]
    runtime_mode = os.getenv("PHARMA_RUNTIME_MODE", "live").lower()
    if runtime_mode == "gptr":
        runtime_mode = "live"
    if runtime_mode == "demo":
        runtime_mode = "replay"
    if runtime_mode not in ("replay", "live"):
        raise HTTPException(503, detail={"code": "RUNTIME_MODE_INVALID", "message": "PHARMA_RUNTIME_MODE must be replay or live"})
    rid = uid(); run = {"id": rid, "workspace_id": workspace_id, "created_at": now(), "created_by": ctx["user"]["id"], "status": "queued", "question": p["question"], "frozen_request": p, "runtime_mode": runtime_mode, "budget": p.get("budget", {}), "usage": {"tool_calls": 0, "model_calls": 0, "input_tokens": None, "output_tokens": None, "usage_quality": "unknown", "estimated_cost": None, "currency": None}, "coverage": [], "checkpoint_ref": None, "attempt": 0 if runtime_mode=="live" else 1, "stop_reason": None, "report_id": None, "event_seq": 0, "next_event_seq": 0, "updated_at": now()}
    state.runs[rid] = run
    emit(rid, "run.queued", {"runtime_mode": runtime_mode})
    if runtime_mode == "live":
        state.idempotency[key] = (state.hash(p), run)
        return JSONResponse(status_code=202, content=run_contract(run))
    run["status"] = "running"
    emit(rid, "run.started", {"runtime_mode": runtime_mode})
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


async def _execute_live_run(run_id: str, request_payload: dict[str, Any]) -> None:
    run = state.runs.get(run_id)
    if not run or run.get("status") == "cancelled": return
    ws = run["workspace_id"]
    run.update(status="running", attempt=int(run.get("attempt",0))+1)
    emit(run_id, "run.started", {"runtime_mode":"live"})
    checkpoint()
    try:
        if not execution_authorized(ws,run["created_by"]):
            run.update(status="failed",error_code="OWNER_PERMISSION_REVOKED",stop_reason="OWNER_PERMISSION_REVOKED")
            emit(run_id,"run.failed",{"error_code":"OWNER_PERMISSION_REVOKED","message":"Run owner no longer has research permission"})
            return
        allowed = {x["record_id"] for x in state.links.values() if x.get("workspace_id")==ws
                   and x.get("drug_id") in request_payload["drug_ids"] and x.get("status")=="approved"}
        evidence=[]
        start, end = request_payload["time_range"]["start"],request_payload["time_range"]["end_exclusive"]
        observed_snapshots={o.get("snapshot_id") for o in state.observations.values() if o.get("workspace_id")==ws
            and o.get("outcome")!="failed" and o.get("fetched_at") and parse_time(start)<=parse_time(o["fetched_at"])<parse_time(end)}
        for item in state.evidence.values():
            snap=state.snapshots.get(item.get("snapshot_id"),{})
            record=state.records.get(snap.get("record_id"),{})
            observed=snap.get("first_observed_at") or snap.get("created_at")
            if (item.get("workspace_id")==ws and record.get("id") in allowed
                and record.get("source") in request_payload["source_allowlist"]
                and snap.get("id") in observed_snapshots):
                evidence.append({**item,"evidence_id":item["id"],"source":record["source"],
                    "normalized":snap.get("normalized",{}),"text":item.get("quoted_text") or item.get("excerpt") or json.dumps(snap.get("normalized",{}),ensure_ascii=False)})
        async def sink(typ, payload):
            emit(run_id,typ,payload)
            if typ.startswith("tool."):
                calls=state.tool_calls.setdefault(run_id,[])
                calls.append({"id":uid(),"workspace_id":ws,"run_id":run_id,"seq":len(calls)+1,"type":typ,"created_at":now(),**payload})
            if payload.get("usage"): run["usage"]=payload["usage"]
            if typ=="research.checkpoint": run["checkpoint"]=payload
            checkpoint()
        budget=ResearchBudget.from_mapping(request_payload.get("budget"), usage=run.get("usage"))
        for field in ("model_calls","tool_calls","records"):
            if hasattr(budget,field): setattr(budget,field,int(run.get("usage",{}).get(field,0) or 0))
        context=ResearchContext(workspace_id=ws,run_id=run_id,question=run["question"],
            source_allowlist=request_payload["source_allowlist"],drug_ids=request_payload["drug_ids"],
            time_range=request_payload["time_range"],budget=budget,evidence=evidence,emit=sink,checkpoint=run.get("checkpoint"))
        deadline=run.setdefault("deadline_at",(datetime.now(timezone.utc)+timedelta(seconds=budget.timeout_seconds)).isoformat())
        checkpoint()
        remaining=(parse_time(deadline)-datetime.now(timezone.utc)).total_seconds()
        if remaining<=0: raise TimeoutError("Research deadline expired during restart")
        result=await asyncio.wait_for(execute_live_research(context),timeout=remaining)
        content=result.get("report")
        if not isinstance(content,dict): raise ValueError("Researcher must return a structured report")
        validate_report_content(ws,content)
        # Deterministic identifiers prevent duplicate reports after recovery.
        report_id=str(uuid.uuid5(uuid.NAMESPACE_URL,run_id+":report"))
        version_id=str(uuid.uuid5(uuid.NAMESPACE_URL,run_id+":v1"))
        if version_id not in state.versions:
            state.reports[report_id]={"id":report_id,"workspace_id":ws,"created_at":now(),"run_id":run_id,
                "title":content["title"],"created_by":run["created_by"],"state":"draft",
                "current_version_id":version_id,"published_version_id":None,"updated_at":now(),"runtime_mode":"live"}
            state.versions[version_id]={"id":version_id,"workspace_id":ws,"created_at":now(),"report_id":report_id,
                "version_no":1,"content":content,"content_hash":state.hash(content),"created_by":run["created_by"],
                "runtime_mode":"live","claim_ids":[uid() for _ in content.get("claims",[])]}
        run.update(status="completed",stop_reason="answered",report_id=report_id,coverage=result.get("coverage",content.get("coverage",[])),usage=result.get("usage",{}))
        emit(run_id,"report.ready",{"report_id":report_id,"runtime_mode":"live"})
        emit(run_id,"run.completed",{"runtime_mode":"live"})
    except asyncio.CancelledError:
        if run.pop("interrupted",False):
            run.update(status="queued",stop_reason="worker_interrupted")
            emit(run_id,"run.interrupted",{"checkpoint":bool(run.get("checkpoint"))})
        else:
            run.update(status="cancelled",stop_reason="cancelled")
            emit(run_id,"run.cancelled",{})
    except Exception as exc:
        code=getattr(exc,"code","RESEARCH_FAILED")
        message=str(exc) if isinstance(exc,(ResearchConfigurationError,GPTResearcherError)) else "Research execution failed; inspect source coverage and model configuration"
        run.update(status="failed",stop_reason=code,error_code=code,error_message=message,
                   gaps=["Research did not finish; completed events and evidence remain available"])
        emit(run_id,"run.failed",{"error_code":code,"message":message})
    finally:
        checkpoint()


def execution_authorized(workspace_id,user_id):
    if state_store:
        from .repository import PersistentStateStore
        observer=PersistentStateStore(state_store.url)
        try: current=observer.load() or {}
        finally: observer.engine.dispose()
        user=current.get("users",{}).get(user_id,{})
        member=current.get("memberships",{}).get(workspace_id+"|"+user_id,{})
    else:
        user=state.users.get(user_id,{})
        member=state.memberships.get((workspace_id,user_id),{})
    return bool(user.get("is_active") and member.get("enabled",True) and member.get("role") in ("analyst","reviewer","admin"))


def checkpoint():
    if state_store is not None: state_store.save(state_payload(state))


def parse_time(value):
    stamp=datetime.fromisoformat(value.replace("Z","+00:00"))
    if stamp.tzinfo is None: raise ValueError("Timezone is required")
    return stamp


def validate_scope(workspace_id, drug_ids, sources, time_range=None):
    if not isinstance(drug_ids,list) or not 1<=len(drug_ids)<=5 or not isinstance(sources,list) or not sources or set(sources)-{"ctgov","pubmed"}:
        raise HTTPException(422,detail={"code":"VALIDATION_ERROR","message":"Select 1–5 drugs and supported sources"})
    for drug in drug_ids: get_drug(workspace_id,drug)
    if time_range:
        try:
            if parse_time(time_range["start"])>=parse_time(time_range["end_exclusive"]): raise ValueError()
            ZoneInfo(time_range["timezone"])
        except (ValueError,KeyError,ZoneInfoNotFoundError):
            raise HTTPException(422,detail={"code":"VALIDATION_ERROR","message":"Invalid time range or IANA timezone"})


def validate_report_content(workspace_id, content):
    import jsonschema
    schema=json.loads((FIXTURES.parent/"contracts/research-output.schema.json").read_text())
    try: jsonschema.validate(content,schema,format_checker=jsonschema.FormatChecker())
    except jsonschema.ValidationError:
        raise HTTPException(422,detail={"code":"INVALID_REPORT","message":"Report does not match ResearchOutput schema"})
    for claim in content.get("claims",[]):
        if claim["category"]=="fact" and not claim.get("evidence_links"):
            raise HTTPException(422,detail={"code":"EVIDENCE_REQUIRED","message":"Facts require versioned evidence"})
        for link in claim.get("evidence_links",[]):
            if state.evidence.get(link["evidence_id"],{}).get("workspace_id")!=workspace_id:
                raise HTTPException(422,detail={"code":"INVALID_EVIDENCE","message":"Evidence is not available in this workspace"})

def get_run(workspace_id: str, run_id: str) -> dict:
    r = state.runs.get(run_id)
    if not r or r.get("workspace_id") != workspace_id:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Research run not found"})
    return r


def visible_run(workspace_id: str, run_id: str, ctx: dict) -> dict:
    run = get_run(workspace_id, run_id)
    if ctx["is_guest"] and run.get("created_by") != ctx["subject_user_id"]:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Research run not found"})
    return run


def usage_contract(usage):
    base={"tool_calls":0,"model_calls":0,"input_tokens":None,"output_tokens":None,"usage_quality":"unknown","estimated_cost":None,"currency":None}
    base.update(usage or {})
    return base


def run_contract(run: dict) -> dict:
    fields = ("id", "workspace_id", "created_at", "created_by", "question", "status", "runtime_mode", "attempt", "frozen_request", "usage", "coverage", "stop_reason", "error_code", "error_message", "event_seq", "report_id", "updated_at")
    return {**{key: run.get(key) for key in fields},"usage":usage_contract(run.get("usage"))}


@app.get("/api/v1/workspaces/{workspace_id}/research/runs")
async def runs_list(workspace_id: str, limit: int = 20, cursor: str | None = None, ctx: dict = Depends(workspace_user)) -> dict:
    if not ctx["is_guest"]: require_role(ctx,"analyst","reviewer","admin")
    return page([run_contract(r) for r in sorted([r for r in state.runs.values()
             if r.get("workspace_id") == workspace_id and (not ctx["is_guest"] or r.get("created_by") == ctx["subject_user_id"])],
             key=lambda x: x.get("created_at", ""), reverse=True)], limit, cursor)


@app.get("/api/v1/workspaces/{workspace_id}/research/runs/{run_id}")
async def run_get(workspace_id: str, run_id: str, ctx: dict = Depends(workspace_user)) -> dict:
    if not ctx["is_guest"]: require_role(ctx,"analyst","reviewer","admin")
    return run_contract(visible_run(workspace_id, run_id, ctx))


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
    source = get_run(workspace_id, run_id)
    if source["status"] not in ("failed","cancelled"): raise HTTPException(409,detail={"code":"INVALID_STATE","message":"Only failed or cancelled runs can be retried"})
    p = await request.json() if request.headers.get("content-length", "0") != "0" else {}
    result = await run_create(workspace_id, _request_with_json({**source.get("frozen_request", {}), **p}), ctx, idempotency_key)
    data=json.loads(result.body) if hasattr(result,"body") else result
    state.runs[data["id"]]["retry_of"]=run_id
    return result


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
    if not ctx["is_guest"]: require_role(ctx,"analyst","reviewer","admin")
    visible_run(workspace_id, run_id, ctx)
    rows=[]
    for call in state.tool_calls.get(run_id,[]):
        rows.append({"id":call["id"],"workspace_id":workspace_id,"created_at":call.get("created_at",now()),"run_id":run_id,
            "tool":call.get("tool",call.get("tool_name","unknown")),"call_key":str(call.get("call_id",call.get("seq"))),
            "state":"completed" if call.get("type")=="tool.completed" else "failed" if call.get("type")=="tool.failed" else "started",
            "arguments_summary":call.get("arguments_summary",call.get("arguments",{})),"evidence_ids":call.get("evidence_ids",[]),
            "error_code":call.get("error_code"),"duration_ms":call.get("duration_ms")})
    return page(rows,limit,cursor)


@app.get("/api/v1/workspaces/{workspace_id}/research/runs/{run_id}/events")
async def run_stream(workspace_id: str, run_id: str, request: Request, last_event_id: str | None = Header(default=None, alias="Last-Event-ID"), ctx: dict = Depends(workspace_user)) -> StreamingResponse:
    if not ctx["is_guest"]: require_role(ctx,"analyst","reviewer","admin")
    visible_run(workspace_id, run_id, ctx)
    try: start = int(last_event_id or request.query_params.get("after", "0"))
    except ValueError: raise HTTPException(422, detail={"code":"VALIDATION_ERROR","message":"Invalid Last-Event-ID"})
    async def stream() -> AsyncIterator[str]:
        position=start
        await asyncio.sleep(0.01)
        while True:
            if ctx["is_guest"] and not state_store:
                current_session = session_for(request)
                if not current_session or not guest_subject(current_session):
                    break
            if state_store:
                # Use a separate repository instance so streaming never changes
                # the request/worker unit-of-work baseline.
                from .repository import PersistentStateStore
                store=PersistentStateStore(state_store.url)
                try: snapshot=store.load() or {}; rows=snapshot.get("run_events",{}).get(run_id,[]); status=snapshot.get("runs",{}).get(run_id,{}).get("status")
                finally: store.engine.dispose()
                if ctx["is_guest"] and not guest_session_valid_in_payload(
                    request.cookies.get("pharmascope_session"), snapshot,
                    guest_id=ctx["user"]["id"], workspace_id=workspace_id,
                    subject_user_id=ctx["subject_user_id"]
                ):
                    break
            else:
                rows=list(state.run_events.get(run_id,[])); status=state.runs[run_id]["status"]
            for event in rows:
                if event["seq"]>position:
                    position=event["seq"]
                    yield f"id: {position}\nevent: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            if status in ("completed","failed","cancelled"): break
            if await request.is_disconnected(): break
            yield ": heartbeat\n\n"
            await asyncio.sleep(1)
    return StreamingResponse(stream(),media_type="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})


def report_for(workspace_id: str, report_id: str) -> dict:
    r = state.reports.get(report_id)
    if not r or r.get("workspace_id") != workspace_id:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Report not found"})
    return r


def report_draft_visible(report,ctx):
    if ctx["is_guest"]:
        return report["created_by"] == ctx["subject_user_id"]
    return ctx["membership"]["role"] in ("reviewer","admin") or report["created_by"]==ctx["user"]["id"] and ctx["membership"]["role"]!="reader"


def report_contract(report: dict) -> dict:
    fields = ("id", "workspace_id", "created_at", "run_id", "title", "created_by", "state", "current_version_id", "published_version_id", "updated_at")
    return {key: report.get(key) for key in fields}


@app.get("/api/v1/workspaces/{workspace_id}/reports")
async def reports_list(workspace_id: str, state_filter: str | None = Query(default=None, alias="state"), limit: int = 20, cursor: str | None = None, ctx: dict = Depends(workspace_user)) -> dict:
    rows = [r for r in state.reports.values() if r.get("workspace_id") == workspace_id and (state_filter is None or r.get("state") == state_filter)]
    rows=[r for r in rows if report_draft_visible(r,ctx) or r.get("published_version_id")]
    return page([report_contract(r) for r in rows], limit, cursor)


@app.get("/api/v1/workspaces/{workspace_id}/reports/{report_id}")
async def report_get(workspace_id: str, report_id: str, ctx: dict = Depends(workspace_user)) -> dict:
    raw = report_for(workspace_id, report_id)
    if not report_draft_visible(raw,ctx) and not raw.get("published_version_id"):
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Report not found"})
    r = report_contract(copy.deepcopy(raw))
    if not report_draft_visible(raw,ctx): r["current_version_id"] = None
    return r


@app.get("/api/v1/workspaces/{workspace_id}/reports/{report_id}/versions")
async def versions_list(workspace_id: str, report_id: str, limit: int = 20, cursor: str | None = None, ctx: dict = Depends(workspace_user)) -> dict:
    report_for(workspace_id, report_id); rows = [v for v in state.versions.values() if v.get("workspace_id") == workspace_id and v.get("report_id") == report_id]
    if not report_draft_visible(report_for(workspace_id,report_id),ctx): rows = [v for v in rows if v["id"] == report_for(workspace_id, report_id).get("published_version_id")]
    return page(rows, limit, cursor)


@app.post("/api/v1/workspaces/{workspace_id}/reports/{report_id}/versions")
async def version_create(workspace_id: str, report_id: str, request: Request, ctx: dict = Depends(csrf)) -> dict:
    require_role(ctx, "analyst", "reviewer", "admin")
    report = report_for(workspace_id, report_id); p = await request.json(); content = p.get("content")
    if not isinstance(content, dict) or not p.get("base_version_id") or not p.get("edit_note"):
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "base_version_id, content and edit_note are required"})
    base = state.versions.get(p["base_version_id"])
    if not base or base.get("report_id") != report_id or base["id"] != report.get("current_version_id"):
        raise HTTPException(409, detail={"code": "STALE_VERSION", "message": "Base report version is not current"})
    if report["created_by"] != ctx["user"]["id"] and ctx["membership"]["role"] == "analyst":
        raise HTTPException(403,detail={"code":"FORBIDDEN","message":"Only the author may edit this draft"})
    validate_report_content(workspace_id,content)
    versions = [v for v in state.versions.values() if v.get("report_id") == report_id]; v = {"id": uid(), "workspace_id": workspace_id, "created_at": now(), "report_id": report_id, "version_no": len(versions) + 1, "content": content, "content_hash": state.hash(content), "created_by": ctx["user"]["id"], "runtime_mode": base.get("runtime_mode", os.getenv("PHARMA_RUNTIME_MODE", "live")), "claim_ids": [uid() for _ in content.get("claims", [])]}
    state.versions[v["id"]] = v; report["current_version_id"] = v["id"]; report["state"] = "draft"; report["updated_at"] = now(); return JSONResponse(status_code=201, content=v)


@app.get("/api/v1/workspaces/{workspace_id}/reports/{report_id}/versions/{version_id}")
async def version_get(workspace_id: str, report_id: str, version_id: str, ctx: dict = Depends(workspace_user)) -> dict:
    report_for(workspace_id, report_id); v = state.versions.get(version_id)
    if not v or v.get("report_id") != report_id or (not report_draft_visible(report_for(workspace_id,report_id),ctx) and v["id"] != report_for(workspace_id, report_id).get("published_version_id")):
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Report version not found"})
    return v


@app.post("/api/v1/workspaces/{workspace_id}/reports/{report_id}/submit-review")
async def submit_review(workspace_id: str, report_id: str, request: Request, ctx: dict = Depends(csrf)) -> dict:
    require_role(ctx, "analyst", "reviewer", "admin")
    r = report_for(workspace_id, report_id)
    if r["state"] not in ("draft","changes_requested"): raise HTTPException(409,detail={"code":"INVALID_STATE","message":"Only a draft can be submitted"})
    if r["created_by"] != ctx["user"]["id"] and ctx["membership"]["role"]=="analyst": raise HTTPException(403,detail={"code":"FORBIDDEN","message":"Only the author can submit this report"})
    r["state"] = "in_review"; r["submitted_at"] = now(); r["updated_at"] = r["submitted_at"]; return report_contract(r)


@app.get("/api/v1/workspaces/{workspace_id}/reports/{report_id}/reviews")
async def reviews_list(workspace_id: str, report_id: str, limit: int = 20, cursor: str | None = None, ctx: dict = Depends(workspace_user)) -> dict:
    report_for(workspace_id, report_id); return page([{k:v for k,v in x.items() if k!="report_id"} for x in state.reviews.values() if x["workspace_id"] == workspace_id and x["report_id"] == report_id], limit, cursor)


@app.post("/api/v1/workspaces/{workspace_id}/reports/{report_id}/reviews")
async def review_create(workspace_id: str, report_id: str, request: Request, ctx: dict = Depends(csrf)) -> dict:
    require_role(ctx, "reviewer", "admin")
    r = report_for(workspace_id, report_id); p = await request.json(); vid, ch = p.get("version_id"), p.get("content_hash"); v = state.versions.get(vid)
    if p.get("decision")=="request_changes": p["decision"]="reject"
    if p.get("decision") not in ("approve", "reject") or not p.get("note"):
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "decision and note are required"})
    if not v or v.get("report_id") != report_id or v.get("content_hash") != ch: raise HTTPException(409, detail={"code": "STALE_VERSION", "message": "Version hash does not match"})
    if ctx["user"]["id"] in (v.get("created_by"), r.get("created_by")): raise HTTPException(409, detail={"code": "SELF_REVIEW_FORBIDDEN", "message": "Author cannot review own version"})
    if p.get("decision") not in ("approve", "reject") or not isinstance(p.get("note"), str) or not p["note"].strip():
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "decision and note are required"})
    if r["state"] != "in_review" or vid != r.get("current_version_id"): raise HTTPException(409,detail={"code":"INVALID_STATE","message":"Review requires the current submitted version"})
    rv = {"id": uid(), "workspace_id": workspace_id, "created_at": now(), "report_id": report_id, "version_id": vid, "content_hash": ch, "decision": p["decision"], "note": p["note"], "reviewer_id": ctx["user"]["id"]}; state.reviews[rv["id"]] = rv; r["state"] = "approved" if rv["decision"] == "approve" else "changes_requested"; return JSONResponse(status_code=201,content={k:v for k,v in rv.items() if k!="report_id"})


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
    if r.get("state") != "approved" or r.get("current_version_id") != vid: raise HTTPException(409,detail={"code":"STALE_VERSION","message":"Publish requires the current approved version"})
    if not approved: raise HTTPException(409, detail={"code": "REPORT_NOT_APPROVED", "message": "Report version has not been approved"})
    r.update({"published_version_id": vid, "current_version_id": vid, "state": "published", "published_at": now(), "published_by": ctx["user"]["id"], "updated_at": now()})
    queue_report_deliveries(r,v)
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
    if not v or v.get("report_id")!=report_id or v.get("workspace_id")!=workspace_id or (not report_draft_visible(r,ctx) and (vid!=r.get("published_version_id") or r.get("state")=="retracted")): raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Version not found"})
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


def queue_report_deliveries(report,version):
    run=state.runs.get(report["run_id"],{})
    recipients={(report["created_by"],"in_app")}
    for sub in state.subscriptions.values():
        if sub["workspace_id"]==report["workspace_id"] and sub.get("enabled") and set(sub["drug_ids"])&set(run.get("frozen_request",{}).get("drug_ids",[])):
            for channel in sub["channels"]: recipients.add((sub["owner_id"],channel))
    for recipient,channel in recipients:
        if not membership(report["workspace_id"],state.users.get(recipient,{})): continue
        key=str(uuid.uuid5(uuid.NAMESPACE_URL,version["id"]+recipient+channel))
        state.deliveries.setdefault(key,{"id":key,"workspace_id":report["workspace_id"],"created_at":now(),
            "recipient_user_id":recipient,"report_id":report["id"],"version_id":version["id"],
            "report_version_id":version["id"],"error_code":None,"accepted_at":now() if channel=="in_app" else None,
            "channel":channel,"state":"delivered" if channel=="in_app" else "queued",
            "subject":report["title"],"title":report["title"],"attempt":0,"read_at":None,
            "delivered_at":now() if channel=="in_app" else None})
    for occurrence in state.occurrences.values():
        if occurrence.get("run_id")==report["run_id"]:
            occurrence["state"]="delivered"
            sub=state.subscriptions.get(occurrence["subscription_id"])
            if sub: sub["last_delivered_at"]=now(); sub["last_outcome"]="delivered"


def schedule_occurrences(payload: dict) -> list[dict]:
    schedule = payload.get("schedule", payload)
    freq, tz_name, local_time = schedule.get("frequency"), schedule.get("timezone"), schedule.get("local_time")
    if freq not in ("daily", "weekly") or not isinstance(local_time, str) or not isinstance(tz_name, str):
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "frequency, local_time and timezone are required"})
    try:
        zone = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": f"Unknown IANA timezone: {tz_name}"}) from exc
    try:
        hour, minute = (int(x) for x in local_time.split(":", 1))
        if not 0 <= hour <= 23 or not 0 <= minute <= 59: raise ValueError
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "local_time must be HH:MM"}) from exc
    weekday = schedule.get("weekday")
    if (freq == "weekly" and (not isinstance(weekday, int) or not 1<=weekday<=7)) or (freq == "daily" and weekday is not None):
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "weekday must match frequency"})
    now_local = datetime.now(timezone.utc).astimezone(zone).replace(second=0, microsecond=0)
    out: list[dict] = []
    for offset in range(0, 40):
        candidate = (now_local + timedelta(days=offset)).replace(hour=hour, minute=minute)
        if candidate <= now_local: continue
        if freq == "weekly" and candidate.isoweekday() != weekday: continue
        utc = candidate.astimezone(timezone.utc)
        roundtrip = utc.astimezone(zone)
        adjusted = roundtrip.replace(tzinfo=None) != candidate.replace(tzinfo=None)
        if adjusted: candidate = roundtrip
        out.append({"utc": utc.isoformat().replace("+00:00", "Z"), "local": candidate.strftime("%Y-%m-%d %H:%M"), "dst_adjusted": adjusted or candidate.utcoffset() != (candidate.replace(fold=1).utcoffset())})
        if len(out) == 5: break
    return out


@app.get("/api/v1/workspaces/{workspace_id}/subscriptions")
async def subscriptions(workspace_id: str, limit: int = 20, cursor: str | None = None, ctx: dict = Depends(workspace_user)) -> dict:
    return page([s for s in state.subscriptions.values() if s["workspace_id"] == workspace_id and (s["owner_id"]==ctx["subject_user_id"] or ctx["membership"]["role"]=="admin")], limit, cursor)


@app.post("/api/v1/workspaces/{workspace_id}/subscriptions")
async def subscription_create(workspace_id: str, request: Request, ctx: dict = Depends(csrf)) -> dict:
    require_role(ctx, "analyst", "reviewer", "admin"); p = await request.json();
    if not p.get("name") or not p.get("drug_ids") or not p.get("schedule"): raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "name, drug_ids and schedule are required"})
    validate_scope(workspace_id,p["drug_ids"],p.get("source_allowlist",["ctgov","pubmed"]))
    if not p.get("channels",["in_app"]) or set(p.get("channels",["in_app"]))-{"in_app","email"}: raise HTTPException(422,detail={"code":"VALIDATION_ERROR","message":"Unsupported channel"})
    s = {"id": uid(), "workspace_id": workspace_id, "created_at": now(), "name": p["name"], "drug_ids": p["drug_ids"], "source_allowlist": p.get("source_allowlist", ["ctgov", "pubmed"]), "schedule": p["schedule"], "channels": p.get("channels", ["in_app"]), "enabled": p.get("enabled", True), "owner_id": ctx["user"]["id"], "revision": 1, "next_run_at": schedule_occurrences(p)[0]["utc"], "last_outcome": None}; state.subscriptions[s["id"]] = s; return JSONResponse(status_code=201, content=s)


@app.post("/api/v1/workspaces/{workspace_id}/subscriptions/preview")
async def subscription_preview(workspace_id: str, request: Request, ctx: dict = Depends(csrf)) -> dict:
    await workspace_user(workspace_id, ctx["user"]); return {"occurrences": schedule_occurrences(await request.json())}


@app.get("/api/v1/workspaces/{workspace_id}/subscriptions/{subscription_id}")
async def subscription_get(workspace_id: str, subscription_id: str, ctx: dict = Depends(workspace_user)) -> dict:
    s = state.subscriptions.get(subscription_id)
    if not s or s["workspace_id"] != workspace_id or (s["owner_id"]!=ctx["subject_user_id"] and ctx["membership"]["role"]!="admin"): raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Subscription not found"})
    return s


@app.patch("/api/v1/workspaces/{workspace_id}/subscriptions/{subscription_id}")
async def subscription_update(workspace_id: str, subscription_id: str, request: Request, ctx: dict = Depends(csrf), if_match: str | None = Header(default=None, alias="If-Match")) -> dict:
    require_role(ctx, "analyst", "reviewer", "admin"); s = await subscription_get(workspace_id, subscription_id, ctx); p = await request.json()
    if if_match and if_match.strip('"') != str(s["revision"]): raise HTTPException(409, detail={"code": "STALE_VERSION", "message": "Subscription revision is stale"})
    validate_scope(workspace_id,p.get("drug_ids",s["drug_ids"]),p.get("source_allowlist",s["source_allowlist"]))
    schedule_occurrences({**s,**p})
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
    rows = [d for d in state.deliveries.values() if d["workspace_id"] == workspace_id and d["recipient_user_id"] == ctx["subject_user_id"]]; return page(rows, limit, cursor)


@app.post("/api/v1/workspaces/{workspace_id}/inbox/{delivery_id}/read")
async def inbox_read(workspace_id: str, delivery_id: str, ctx: dict = Depends(csrf)) -> dict:
    d = state.deliveries.get(delivery_id)
    if not d or d["workspace_id"] != workspace_id or d["recipient_user_id"] != ctx["user"]["id"]: raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Delivery not found"})
    d["read_at"] = now(); return d


@app.get("/api/v1/workspaces/{workspace_id}/deliveries")
async def deliveries(workspace_id: str, limit: int = 20, cursor: str | None = None, ctx: dict = Depends(workspace_user)) -> dict:
    return page([d for d in state.deliveries.values() if d["workspace_id"] == workspace_id and (d["recipient_user_id"]==ctx["subject_user_id"] or ctx["membership"]["role"]=="admin")], limit, cursor)


@app.get("/api/v1/workspaces/{workspace_id}/deliveries/{delivery_id}")
async def delivery_get(workspace_id: str, delivery_id: str, ctx: dict = Depends(workspace_user)) -> dict:
    d = state.deliveries.get(delivery_id)
    if not d or d["workspace_id"] != workspace_id or (d["recipient_user_id"]!=ctx["subject_user_id"] and ctx["membership"]["role"]!="admin"): raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Delivery not found"})
    return d


@app.post("/api/v1/workspaces/{workspace_id}/deliveries/{delivery_id}/retry")
async def delivery_retry(workspace_id: str, delivery_id: str, ctx: dict=Depends(csrf)) -> dict:
    require_role(ctx,"admin")
    delivery=state.deliveries.get(delivery_id)
    if not delivery or delivery["workspace_id"]!=workspace_id: raise HTTPException(404,detail={"code":"NOT_FOUND","message":"Delivery not found"})
    if delivery.get("state") not in ("failed","disabled","dry_run"): raise HTTPException(409,detail={"code":"INVALID_STATE","message":"Delivery is not retryable"})
    delivery.update(state="queued",error_code=None)
    return delivery


@app.get("/api/v1/workspaces/{workspace_id}/audit")
async def audit(workspace_id: str, action: str | None = None, limit: int = 20, cursor: str | None = None, ctx: dict = Depends(workspace_user)) -> dict:
    require_role(ctx,"admin","reviewer")
    return page([{"id":a["id"],"workspace_id":workspace_id,"created_at":a["created_at"],"actor_id":a.get("actor_id",a.get("actor_user_id")),
        "action":a["action"],"target_type":a.get("target_type",a.get("resource_type","workspace")),"target_id":a.get("target_id"),
        "details":a.get("details",{"request_id":a.get("request_id"),"result":a.get("result")})}
        for a in state.audit if a["workspace_id"] == workspace_id and (action is None or a["action"] == action)], limit, cursor)


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
