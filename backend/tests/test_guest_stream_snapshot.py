"""Open guest streams must use committed authorization, not API process memory."""

import copy
import time

from backend import pharma_scope_app as api
from backend.repository import state_payload


def test_guest_stream_snapshot_rechecks_session_and_demo_selection(monkeypatch):
    monkeypatch.setenv("PHARMA_RUNTIME_MODE", "replay")
    state = api.DomainState()
    token = "guest-stream-cookie"
    guest_id = api.uid()
    state.sessions[api.session_key(token)] = {
        "guest": True,
        "guest_id": guest_id,
        "user_id": api.DEFAULT_USER,
        "workspace_id": api.DEFAULT_WORKSPACE,
        "expires_at": time.time() + 3600,
    }
    committed = state_payload(state)

    def valid(snapshot):
        return api.guest_session_valid_in_payload(
            token, snapshot, guest_id=guest_id,
            workspace_id=api.DEFAULT_WORKSPACE, subject_user_id=api.DEFAULT_USER,
        )

    assert valid(committed)
    assert not api.guest_session_valid_in_payload(
        token, committed, guest_id=api.uid(),
        workspace_id=api.DEFAULT_WORKSPACE, subject_user_id=api.DEFAULT_USER,
    )

    revoked = copy.deepcopy(committed)
    revoked["sessions"].clear()
    assert not valid(revoked)

    expired = copy.deepcopy(committed)
    expired["sessions"][api.session_key(token)]["expires_at"] = time.time() - 1
    assert not valid(expired)

    switched = copy.deepcopy(committed)
    switched["workspaces"][api.DEFAULT_WORKSPACE]["public_demo"] = False
    switched["workspaces"][api.SECOND_WORKSPACE]["public_demo"] = True
    assert not valid(switched)

    changed_account = copy.deepcopy(committed)
    changed_account["workspaces"][api.DEFAULT_WORKSPACE]["demo_user_id"] = api.REVIEWER_USER
    assert not valid(changed_account)

    disabled_member = copy.deepcopy(committed)
    disabled_member["memberships"][api.DEFAULT_WORKSPACE + "|" + api.DEFAULT_USER]["enabled"] = False
    assert not valid(disabled_member)

    # Process memory still has the original grant; only the committed copy changed.
    assert valid(committed)
