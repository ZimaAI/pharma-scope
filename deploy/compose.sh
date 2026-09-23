#!/usr/bin/env bash
# Load one explicit environment for both Compose interpolation and containers.
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="${1:?Usage: deploy/compose.sh ENV_FILE [compose arguments ...]}"
shift
[[ -f "$CONFIG" ]] || { echo "Environment file not found: $CONFIG" >&2; exit 2; }
export PHARMA_ENV_FILE="$(realpath -- "$CONFIG")"
exec docker compose --project-name pharmascope --env-file "$PHARMA_ENV_FILE" -f "$ROOT/deploy/docker-compose.yml" "$@"
