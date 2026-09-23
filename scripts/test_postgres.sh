#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ -z "${PHARMA_TEST_DATABASE_URL:-}" ]]; then
  bash deploy/test-postgres.sh start
  export PHARMA_TEST_DATABASE_URL="postgresql+psycopg://pharma_test@127.0.0.1:${PHARMA_TEST_PG_PORT:-18432}/pharmascope_test"
fi
exec .venv/bin/python -m pytest -q backend/tests/test_postgres_integration.py "$@"
