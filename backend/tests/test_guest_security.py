"""Security boundaries for an administrator-selected, read-only guest session."""

import copy

import pytest
from fastapi.testclient import TestClient

from backend import pharma_scope_app as api


WORKSPACE = f"/api/v1/workspaces/{api.DEFAULT_WORKSPACE}"


@pytest.fixture
def clients(monkeypatch):
    monkeypatch.setenv("PHARMA_RUNTIME_MODE", "replay")
    monkeypatch.setenv("PHARMA_COOKIE_SECURE", "0")
    monkeypatch.delenv("PHARMA_ALLOW_DEV_HEADER", raising=False)
    monkeypatch.setattr(api, "state", api.DomainState())
    monkeypatch.setattr(api, "state_store", None)
    monkeypatch.setattr(api, "persistence_error", None)
    with TestClient(api.app) as admin, TestClient(api.app) as guest:
        yield admin, guest


def select_demo_account(admin: TestClient, user_id: str = api.DEFAULT_USER) -> None:
    login = admin.post(
        "/api/v1/auth/login",
        json={"email": "admin@pharmascope.invalid", "password": "demo"},
    )
    assert login.status_code == 200, login.text
    selected = admin.patch(
        WORKSPACE + "/settings/demo-account",
        headers={"X-CSRF-Token": login.json()["csrf_token"]},
        json={"user_id": user_id},
    )
    assert selected.status_code == 200, selected.text


def guest_login(guest: TestClient) -> dict:
    response = guest.post("/api/v1/auth/guest-login")
    assert response.status_code == 200, response.text
    assert "httponly" in response.headers["set-cookie"].lower()
    return response.json()


def test_guest_can_read_selected_account_but_cannot_change_it(clients):
    admin, guest = clients
    select_demo_account(admin)
    delivery_id = "guest-read-only-delivery"
    api.state.deliveries[delivery_id] = {
        "id": delivery_id,
        "workspace_id": api.DEFAULT_WORKSPACE,
        "recipient_user_id": api.DEFAULT_USER,
        "state": "delivered",
        "read_at": None,
    }

    session = guest_login(guest)
    assert session["is_guest"] is True
    assert session["memberships"][0]["role"] == "reader"
    assert guest.get(WORKSPACE + "/dashboard").status_code == 200
    assert guest.get(WORKSPACE + "/members").status_code == 403
    inbox = guest.get(WORKSPACE + "/inbox")
    assert inbox.status_code == 200, inbox.text
    assert delivery_id in {item["id"] for item in inbox.json()["items"]}

    csrf = {"X-CSRF-Token": session["csrf_token"]}
    drugs_before = copy.deepcopy(api.state.drugs)
    for method, path, body in (
        ("POST", "/drugs", {"display_name": "Forbidden guest edit"}),
        ("POST", f"/inbox/{delivery_id}/read", None),
        ("POST", "/subscriptions/preview", {"schedule": {"frequency": "daily", "timezone": "UTC", "local_time": "09:00"}}),
        ("PATCH", f"/members/{api.DEFAULT_USER}", {"role": "admin"}),
    ):
        response = guest.request(method, WORKSPACE + path, headers=csrf, json=body)
        assert response.status_code == 403, (path, response.text)
    assert api.state.drugs == drugs_before
    assert api.state.deliveries[delivery_id]["read_at"] is None
    assert api.state.memberships[(api.DEFAULT_WORKSPACE, api.DEFAULT_USER)]["role"] == "analyst"


def test_guest_session_stops_when_admin_changes_demo_account(clients):
    admin, guest = clients
    select_demo_account(admin)
    guest_login(guest)
    csrf = admin.get("/api/v1/auth/me").json()["csrf_token"]
    changed = admin.patch(
        WORKSPACE + "/settings/demo-account",
        headers={"X-CSRF-Token": csrf},
        json={"user_id": api.REVIEWER_USER},
    )
    assert changed.status_code == 200, changed.text
    assert guest.get("/api/v1/auth/me").status_code == 401
    assert guest.get(WORKSPACE + "/dashboard").status_code == 401


def test_switching_demo_workspace_revokes_old_guest_and_limits_new_guest(clients):
    admin, old_guest = clients
    select_demo_account(admin)
    guest_login(old_guest)

    second = f"/api/v1/workspaces/{api.SECOND_WORKSPACE}"
    csrf = admin.get("/api/v1/auth/me").json()["csrf_token"]
    changed = admin.patch(
        second + "/settings/demo-account",
        headers={"X-CSRF-Token": csrf},
        json={"user_id": api.ADMIN_USER},
    )
    assert changed.status_code == 200, changed.text
    assert old_guest.get("/api/v1/auth/me").status_code == 401
    assert admin.get(WORKSPACE + "/settings/demo-account").json()["enabled"] is False

    with TestClient(api.app) as new_guest:
        session = guest_login(new_guest)
        assert session["memberships"] == [{
            "workspace_id": api.SECOND_WORKSPACE,
            "workspace_name": api.state.workspaces[api.SECOND_WORKSPACE]["name"],
            "role": "reader",
        }]
        assert new_guest.get(second + "/dashboard").status_code == 200
        assert new_guest.get(WORKSPACE + "/dashboard").status_code == 404
        assert new_guest.get(second + "/audit").status_code == 403


def test_replay_header_cannot_impersonate_admin_by_default(clients):
    _, guest = clients
    response = guest.get(
        WORKSPACE + "/audit",
        headers={"X-User-Id": api.ADMIN_USER},
    )
    assert response.status_code == 401
