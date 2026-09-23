#!/usr/bin/env bash
# Read-only smoke checks: no services, database rows or Nginx files are changed.
set -Eeuo pipefail
ORIGIN="${1:-https://pharmascope.zimagent.top}"
API_ORIGIN="${2:-http://127.0.0.1:18180}"
check() {
  printf '%-18s ' "$1"
  curl --fail --silent --show-error --max-time 10 "$2" >/dev/null
  echo PASS
}
check api-health "$API_ORIGIN/healthz"
check api-ready "$API_ORIGIN/readyz"
check public-health "$ORIGIN/healthz"
check public-ready "$ORIGIN/readyz"
check static-frontend "$ORIGIN/"
headers="$(curl --silent --show-error --max-time 10 -D - -o /dev/null "$ORIGIN/api/v1/auth/me")"
grep -qi '^HTTP/.* 401 ' <<<"$headers" || { echo 'auth status check failed' >&2; exit 1; }
grep -qi '^x-request-id:' <<<"$headers" || { echo 'request id header missing' >&2; exit 1; }
echo 'auth-boundary      PASS'
if [[ "$ORIGIN" == https://* ]]; then
  headers="$(curl --silent --show-error --max-time 10 -D - -o /dev/null "http://${ORIGIN#https://}/healthz")"
  grep -qi '^location: https://' <<<"$headers" || { echo 'HTTP to HTTPS redirect check failed' >&2; exit 1; }
  echo 'https-redirect     PASS'
fi
# Supply a same-origin run-events PATH and a PRIVATE curl cookie jar to verify a
# real authenticated SSE stream. The script never creates a research run.
if [[ -n "${PHARMA_VERIFY_SSE_PATH:-}" ]]; then
  [[ "$PHARMA_VERIFY_SSE_PATH" == /api/v1/* ]] || { echo 'SSE path must start with /api/v1/' >&2; exit 2; }
  [[ -r "${PHARMA_VERIFY_COOKIE_FILE:-}" ]] || { echo 'A private cookie jar is required for SSE verification' >&2; exit 2; }
  result="$(mktemp /tmp/pharmascope-sse.XXXXXX)"
  trap 'rm -f "$result"' EXIT
  code=0
  curl --silent --show-error --no-buffer --max-time 5 -D "$result" -b "$PHARMA_VERIFY_COOKIE_FILE" "$ORIGIN$PHARMA_VERIFY_SSE_PATH" >>"$result" || code=$?
  [[ "$code" == 0 || "$code" == 28 ]] || exit "$code"
  grep -qi '^content-type: text/event-stream' "$result" || { echo 'SSE content type missing' >&2; exit 1; }
  grep -Eq '^(data:|:)' "$result" || { echo 'SSE delivered no event or heartbeat' >&2; exit 1; }
  echo 'authenticated-sse  PASS'
else
  echo 'authenticated-sse  NOT_RUN (set PHARMA_VERIFY_SSE_PATH and PHARMA_VERIFY_COOKIE_FILE)'
fi
