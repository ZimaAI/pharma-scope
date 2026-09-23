"""Public deployment must not expose the replay administrator's demo password."""

import subprocess
import sys
from pathlib import Path


CHECK = Path(__file__).resolve().parents[2] / "deploy" / "check-public-config.py"
BASE = {
    "PHARMA_DATABASE_URL": "postgresql+psycopg://user:pass@localhost/db",
    "PHARMA_COOKIE_SECURE": "1",
    "PHARMA_PUBLIC_ORIGIN": "https://pharmascope.zimagent.top",
}


def check(mode: str, password: str | None) -> subprocess.CompletedProcess[str]:
    values = {**BASE, "PHARMA_RUNTIME_MODE": mode}
    if password is not None:
        values["PHARMA_DEMO_PASSWORD"] = password
    return subprocess.run(
        [sys.executable, str(CHECK)], env=values, text=True, capture_output=True,
        check=False,
    )


def test_public_replay_rejects_missing_or_short_demo_password_without_printing_it():
    for password in (None, "tiny-secret"):
        result = check("replay", password)
        assert result.returncode == 1
        assert "PHARMA_DEMO_PASSWORD" in result.stderr
        if password:
            assert password not in result.stderr


def test_public_replay_accepts_strong_demo_password_and_live_does_not_need_one():
    replay = check("replay", "private-demo-password-123")
    assert replay.returncode == 0 and replay.stdout.strip() == "replay"
    assert "private-demo-password-123" not in replay.stdout + replay.stderr
    live = check("live", None)
    assert live.returncode == 0 and live.stdout.strip() == "live"
