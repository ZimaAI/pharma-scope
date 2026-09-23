#!/usr/bin/env python3
"""Validate the public deployment environment without exposing secrets."""

import os
import sys
from collections.abc import Mapping


def validate_public_config(values: Mapping[str, str]) -> str:
    mode = values.get("PHARMA_RUNTIME_MODE", "")
    if mode not in ("replay", "live"):
        raise ValueError("PHARMA_RUNTIME_MODE must be replay or live")
    if not values.get("PHARMA_DATABASE_URL", "").startswith("postgres"):
        raise ValueError("PHARMA_DATABASE_URL must configure PostgreSQL")
    if values.get("PHARMA_COOKIE_SECURE") != "1":
        raise ValueError("Public HTTPS deployment requires PHARMA_COOKIE_SECURE=1")
    if values.get("PHARMA_PUBLIC_ORIGIN") != "https://pharmascope.zimagent.top":
        raise ValueError("Set PHARMA_PUBLIC_ORIGIN=https://pharmascope.zimagent.top")
    if mode == "replay" and len(values.get("PHARMA_DEMO_PASSWORD", "")) < 12:
        raise ValueError("Public replay deployment requires PHARMA_DEMO_PASSWORD with at least 12 characters")
    return mode


if __name__ == "__main__":
    try:
        print(validate_public_config(os.environ))
    except ValueError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from None
