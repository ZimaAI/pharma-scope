"""Account administration and sign-in abuse boundaries."""

import pytest
from fastapi.testclient import TestClient

from backend import pharma_scope_app as api


BASE = f"/api/v1/workspaces/{api.DEFAULT_WORKSPACE}"


@pytest.fixture
def clients(monkeypatch):
    monkeypatch.setenv("PHARMA_RUNTIME_MODE", "replay")
    monkeypatch.setenv("PHARMA_COOKIE_SECURE", "0")
    monkeypatch.setattr(api, "state", api.DomainState())
    monkeypatch.setattr(api, "state_store", None)
    monkeypatch.setattr(api, "persistence_error", None)
    with TestClient(api.app) as admin, TestClient(api.app) as member:
        login = admin.post("/api/v1/auth/login", json={"email": "admin@pharmascope.invalid", "password": "demo"})
        assert login.status_code == 200
        yield admin, member, {"X-CSRF-Token": login.json()["csrf_token"]}


def test_admin_creates_resets_and_disables_member(clients):
    admin, member, csrf = clients
    created = admin.post(BASE + "/members", headers=csrf, json={
        "email": "visitor@example.invalid", "display_name": "Visitor",
        "password": "initial-password-123", "role": "analyst",
    })
    assert created.status_code == 201, created.text
    assert "password_hash" not in created.text
    user_id = created.json()["user"]["id"]

    logged_in = member.post("/api/v1/auth/login", json={"email": "visitor@example.invalid", "password": "initial-password-123"})
    assert logged_in.status_code == 200
    reset = admin.post(BASE + f"/members/{user_id}/password", headers=csrf, json={"new_password": "replacement-password-123"})
    assert reset.status_code == 200, reset.text
    assert member.get("/api/v1/auth/me").status_code == 401
    assert member.post("/api/v1/auth/login", json={"email": "visitor@example.invalid", "password": "replacement-password-123"}).status_code == 200

    disabled = admin.patch(BASE + f"/members/{user_id}", headers=csrf, json={"enabled": False})
    assert disabled.status_code == 200, disabled.text
    assert member.get("/api/v1/auth/me").status_code == 401
    assert member.post("/api/v1/auth/login", json={"email": "visitor@example.invalid", "password": "replacement-password-123"}).status_code == 401


def test_last_admin_and_cross_workspace_password_reset_are_protected(clients):
    admin, member, csrf = clients
    second = f"/api/v1/workspaces/{api.SECOND_WORKSPACE}"
    assert admin.patch(second + f"/members/{api.ADMIN_USER}", headers=csrf, json={"enabled": False}).status_code == 409

    actor = admin.post(BASE + "/members", headers=csrf, json={
        "email": "local-admin@example.invalid", "display_name": "Local Admin",
        "password": "admin-password-123", "role": "admin",
    }).json()["user"]
    assert member.post("/api/v1/auth/login", json={"email": actor["email"], "password": "admin-password-123"}).status_code == 200
    local_csrf = {"X-CSRF-Token": member.get("/api/v1/auth/me").json()["csrf_token"]}
    forbidden = member.post(BASE + f"/members/{api.ADMIN_USER}/password", headers=local_csrf,
                            json={"new_password": "takeover-password-123"})
    assert forbidden.status_code == 403, forbidden.text


def test_password_change_requires_current_password_and_throttles_failures(clients):
    _, member, _ = clients
    login = member.post("/api/v1/auth/login", json={"email": "analyst@pharmascope.invalid", "password": "demo"})
    csrf = {"X-CSRF-Token": login.json()["csrf_token"]}
    for _ in range(5):
        bad = member.post("/api/v1/auth/password", headers=csrf,
                          json={"current_password": "incorrect", "new_password": "replacement-password-123"})
        assert bad.status_code == 401
    blocked = member.post("/api/v1/auth/password", headers=csrf,
                          json={"current_password": "demo", "new_password": "replacement-password-123"})
    assert blocked.status_code == 429
    assert api.state.users[api.DEFAULT_USER].get("password_hash") is None


def test_repeated_invalid_sign_in_is_throttled(clients):
    _, member, _ = clients
    for _ in range(5):
        assert member.post("/api/v1/auth/login", json={"email": "unknown@example.invalid", "password": "incorrect"}).status_code == 401
    assert member.post("/api/v1/auth/login", json={"email": "unknown@example.invalid", "password": "incorrect"}).status_code == 429
