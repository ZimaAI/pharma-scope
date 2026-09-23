#!/usr/bin/env python3
"""Check the public guest journey without changing business records."""

from __future__ import annotations

import http.cookiejar
import json
import sys
import urllib.error
import urllib.request


def main() -> None:
    origin = (sys.argv[1] if len(sys.argv) > 1 else "https://pharmascope.zimagent.top").rstrip("/")
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(path: str, *, payload: dict | None = None, csrf: str | None = None):
        headers = {"Accept": "application/json"}
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode()
        if csrf:
            headers["X-CSRF-Token"] = csrf
        req = urllib.request.Request(origin + path, data=data, headers=headers)
        try:
            with opener.open(req, timeout=10) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    status, _ = request("/api/v1/auth/me")
    assert status == 401, f"Unauthenticated /me returned {status}"
    status, guest = request("/api/v1/auth/guest-login", payload={})
    assert status == 200, f"Guest login returned {status}: {guest}"
    assert guest.get("is_guest") or guest.get("user", {}).get("is_guest"), "Guest identity is missing"
    memberships = guest.get("memberships") or []
    assert len(memberships) == 1, "Guest should have exactly one workspace"
    workspace = memberships[0]["workspace_id"]
    csrf = guest.get("csrf_token")
    assert csrf, "Guest CSRF token is missing"
    status, _ = request(f"/api/v1/workspaces/{workspace}/dashboard")
    assert status == 200, f"Guest dashboard returned {status}"
    status, drugs = request(f"/api/v1/workspaces/{workspace}/drugs")
    assert status == 200 and isinstance(drugs.get("items"), list), "Guest drug list is unavailable"
    # The empty payload cannot create a drug even if the guard regresses. With
    # a valid CSRF token, 403 verifies the guest permission boundary itself.
    status, _ = request(f"/api/v1/workspaces/{workspace}/drugs", payload={}, csrf=csrf)
    assert status == 403, f"Guest mutation returned {status} instead of 403"
    status, _ = request("/api/v1/auth/logout", payload={}, csrf=csrf)
    assert status == 200, f"Guest logout returned {status}"
    status, _ = request("/api/v1/auth/me")
    assert status == 401, f"Logged-out /me returned {status}"
    print(f"PASS guest login, one workspace, dashboard, drug list, write denial, logout: {origin}")


if __name__ == "__main__":
    main()
