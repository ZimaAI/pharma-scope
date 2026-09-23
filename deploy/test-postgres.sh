#!/usr/bin/env bash
# Isolated, loopback-only PostgreSQL for integration tests; no sudo or Docker.
set -Eeuo pipefail
PG_BIN="${PHARMA_PG_BIN:-/usr/lib/postgresql/16/bin}"
PG_ROOT="${PHARMA_TEST_PG_ROOT:-/tmp/pharmascope-v1-pg-${USER}}"
PG_PORT="${PHARMA_TEST_PG_PORT:-18432}"
[[ "$PG_PORT" =~ ^[0-9]+$ ]] || { echo 'Invalid port' >&2; exit 2; }
case "${1:-status}" in
  start)
    [[ "$EUID" != 0 ]] || { echo 'Run this test instance as a regular user' >&2; exit 2; }
    install -d -m 0700 "$PG_ROOT"
    if [[ ! -s "$PG_ROOT/data/PG_VERSION" ]]; then
      "$PG_BIN/initdb" -D "$PG_ROOT/data" --auth-local=trust --auth-host=trust --username=pharma_test --encoding=UTF8 --no-locale >"$PG_ROOT/initdb.log"
    fi
    if ! "$PG_BIN/pg_ctl" -D "$PG_ROOT/data" status >/dev/null 2>&1; then
      "$PG_BIN/pg_ctl" -D "$PG_ROOT/data" -l "$PG_ROOT/postgres.log" -o "-h 127.0.0.1 -p $PG_PORT -k $PG_ROOT -c max_connections=30 -c shared_buffers=64MB" start
    fi
    if ! "$PG_BIN/psql" -h 127.0.0.1 -p "$PG_PORT" -U pharma_test -d postgres -Atqc "SELECT 1 FROM pg_database WHERE datname='pharmascope_test'" | grep -qx 1; then
      "$PG_BIN/createdb" -h 127.0.0.1 -p "$PG_PORT" -U pharma_test pharmascope_test
    fi
    echo "postgresql+psycopg://pharma_test@127.0.0.1:$PG_PORT/pharmascope_test"
    ;;
  stop) "$PG_BIN/pg_ctl" -D "$PG_ROOT/data" -m fast stop ;;
  status) "$PG_BIN/pg_ctl" -D "$PG_ROOT/data" status ;;
  *) echo 'Usage: deploy/test-postgres.sh start|stop|status' >&2; exit 2 ;;
esac
