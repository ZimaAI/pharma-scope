#!/usr/bin/env bash
# Upgrade PharmaScope only. Existing Nginx sites and unrelated units are retained.
set -Eeuo pipefail
DOMAIN=pharmascope.zimagent.top
API_PORT=18180
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
TARGET_USER="${SUDO_USER:-$(stat -c '%U' "$REPO_ROOT")}"
ENV_FILE="${PHARMA_ENV_FILE:-/etc/pharmascope/pharmascope.env}"
WEB_BASE=/var/www/pharmascope
ACME_ROOT=/var/www/pharmascope-acme
NGINX_SITE=/etc/nginx/sites-available/pharmascope
NGINX_LINK=/etc/nginx/sites-enabled/pharmascope
log() { printf '\n==> %s\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }
[[ "${1:-}" == --help ]] && { echo 'Usage: sudo PHARMA_ENV_FILE=/etc/pharmascope/pharmascope.env bash deploy/install.sh [--check]'; exit 0; }
[[ "${1:-}" == --check || "$EUID" == 0 ]] || die 'Root is required to install this project’s systemd units and Nginx site. Run the command shown by --help.'
[[ -r "$ENV_FILE" ]] || die "Private configuration missing or unreadable: $ENV_FILE. Copy .env.example.demo or .env.example.live there and configure PostgreSQL first."
ENV_FILE="$(realpath -- "$ENV_FILE")"
[[ -x "$REPO_ROOT/.venv/bin/python" && -x "$REPO_ROOT/.venv/bin/uvicorn" ]] || die 'Run make setup first.'
id "$TARGET_USER" >/dev/null || die "Unknown deployment user: $TARGET_USER"
TARGET_GROUP="$(id -gn "$TARGET_USER")"
PYTHON="$REPO_ROOT/.venv/bin/python"
RUNTIME_MODE="$($PYTHON "$SCRIPT_DIR/env-run.py" "$ENV_FILE" "$PYTHON" "$SCRIPT_DIR/check-public-config.py")"
for command in nginx curl systemctl runuser; do command -v "$command" >/dev/null || die "Missing prerequisite: $command"; done
if ss -ltn "sport = :$API_PORT" | tail -n +2 | grep -q LISTEN; then
  pgrep -af "uvicorn.*backend\.pharma_scope_app:app.*--port ${API_PORT}" >/dev/null || die "Port $API_PORT belongs to another project."
fi
if [[ -e "$NGINX_SITE" ]] && ! grep -q "server_name ${DOMAIN}" "$NGINX_SITE"; then
  die "$NGINX_SITE is not the PharmaScope site; refusing to overwrite it."
fi
if [[ -e "$NGINX_LINK" || -L "$NGINX_LINK" ]]; then
  [[ -L "$NGINX_LINK" && "$(readlink -f "$NGINX_LINK")" == "$NGINX_SITE" ]] || die "$NGINX_LINK belongs to another site."
fi
if [[ "${1:-}" == --check ]]; then
  log "Prerequisites checked; mode=$RUNTIME_MODE, API=127.0.0.1:$API_PORT. No files or services changed."
  exit 0
fi
exec 9>/run/lock/pharmascope-install.lock
flock -n 9 || die "Another PharmaScope installation is running."
cd "$REPO_ROOT"
# systemd can read the secret file as root; only the selected deployment group
# can read it during migration. Never evaluate environment values as shell code.
if [[ "$(dirname -- "$ENV_FILE")" == /etc/pharmascope ]]; then
  chown root:"$TARGET_GROUP" /etc/pharmascope
  chmod 0750 /etc/pharmascope
fi
chown root:"$TARGET_GROUP" "$ENV_FILE"
chmod 0640 "$ENV_FILE"
run_env() { runuser -u "$TARGET_USER" -- "$PYTHON" "$SCRIPT_DIR/env-run.py" "$ENV_FILE" "$@"; }
log 'Install the locked runtime dependencies'
runuser -u "$TARGET_USER" -- "$REPO_ROOT/.venv/bin/pip" install -r "$REPO_ROOT/backend/requirements-runtime.lock"
log 'Build the static frontend using same-origin API requests'
runuser -u "$TARGET_USER" -- env PHARMA_BUILD_ROOT="$REPO_ROOT" PHARMA_BUILD_MODE="$RUNTIME_MODE" bash -lc '
  set -Eeuo pipefail
  if [[ -s "$HOME/.nvm/nvm.sh" ]]; then . "$HOME/.nvm/nvm.sh"; fi
  cd "$PHARMA_BUILD_ROOT"
  npm --prefix frontend/nextjs ci --legacy-peer-deps
  NEXT_PUBLIC_PHARMA_API_URL="" NEXT_PUBLIC_PHARMA_RUNTIME_MODE="$PHARMA_BUILD_MODE" npm --prefix frontend/nextjs run build
'
log 'Back up PostgreSQL and apply migrations (failure stops publication)'
install -d -m 0700 -o "$TARGET_USER" -g "$TARGET_GROUP" /var/backups/pharmascope
run_env "$PYTHON" "$SCRIPT_DIR/backup.py" /var/backups/pharmascope
run_env "$REPO_ROOT/.venv/bin/alembic" upgrade head

log 'Install this project’s units'
for component in api worker; do
  unit="/etc/systemd/system/pharmascope-${component}.service"
  install -m 0644 "$SCRIPT_DIR/pharmascope-${component}.service" "$unit"
  # Paths are passed as arguments and replaced in Python, without sed escaping.
  "$PYTHON" - "$unit" "$TARGET_USER" "$TARGET_GROUP" "$REPO_ROOT" "$ENV_FILE" "$component" <<'PY'
from pathlib import Path
import sys
path, user, group, root, env, component = sys.argv[1:]
command = root + ('/.venv/bin/uvicorn backend.pharma_scope_app:app --host 127.0.0.1 --port 18180 --workers 1' if component == 'api' else '/.venv/bin/python -m backend.worker')
values = {'User': user, 'Group': group, 'WorkingDirectory': root, 'EnvironmentFile': env, 'ExecStart': command}
p = Path(path)
p.write_text('\n'.join(k + '=' + values[k] if (k := line.split('=', 1)[0]) in values else line for line in p.read_text().splitlines()) + '\n')
PY
done
systemctl daemon-reload
systemctl enable pharmascope-api.service pharmascope-worker.service
systemctl restart pharmascope-api.service pharmascope-worker.service
for attempt in {1..30}; do
  if curl --fail --silent --max-time 2 "http://127.0.0.1:$API_PORT/readyz" >/dev/null; then break; fi
  [[ "$attempt" != 30 ]] || die 'API readiness failed; existing public static release retained. Check journalctl -u pharmascope-api.'
  sleep 1
done

log 'Publish a versioned static release'
RELEASE="$WEB_BASE/releases/$(date -u +%Y%m%dT%H%M%S)-$$"
install -d -m 0755 "$WEB_BASE/releases" "$RELEASE" "$ACME_ROOT"
cp -a "$REPO_ROOT/frontend/nextjs/out/." "$RELEASE/"
chown -R root:root "$RELEASE"
chmod -R a+rX "$RELEASE"
if [[ -d "$WEB_BASE/current" && ! -L "$WEB_BASE/current" ]]; then
  mv "$WEB_BASE/current" "$WEB_BASE/releases/legacy-$(date -u +%Y%m%dT%H%M%S)-$$"
fi
ln -sfn "$RELEASE" "$WEB_BASE/current.new"
mv -Tf "$WEB_BASE/current.new" "$WEB_BASE/current"

# Roll back only our Nginx site if validation fails. Existing certificates never
# go through an HTTP-only deployment window. Reload retains other sites/workers.
install_nginx() {
  local template="$1" backup
  backup="$(mktemp /tmp/pharmascope-nginx.XXXXXX)"
  local existed=0
  if [[ -f "$NGINX_SITE" ]]; then cp -a "$NGINX_SITE" "$backup"; existed=1; fi
  install -m 0644 "$template" "$NGINX_SITE"
  ln -sfn "$NGINX_SITE" "$NGINX_LINK"
  if ! nginx -t; then
    if [[ "$existed" == 1 ]]; then cp -a "$backup" "$NGINX_SITE"; else rm -f "$NGINX_LINK" "$NGINX_SITE"; fi
    rm -f "$backup"
    die 'Nginx validation failed. The previous PharmaScope site was restored; Nginx was not reloaded.'
  fi
  rm -f "$backup"
  systemctl reload nginx
}
has_tls() { [[ -s "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" && -s "/etc/letsencrypt/live/$DOMAIN/privkey.pem" ]]; }
if has_tls; then
  install_nginx "$SCRIPT_DIR/pharmascope.nginx.conf"
else
  install_nginx "$SCRIPT_DIR/pharmascope.nginx.initial.conf"
  if [[ "${PHARMA_SKIP_TLS:-0}" != 1 ]] && command -v certbot >/dev/null; then
    args=(certonly --webroot -w "$ACME_ROOT" -d "$DOMAIN" --non-interactive --agree-tos)
    if [[ -n "${ACME_EMAIL:-}" ]]; then args+=(--email "$ACME_EMAIL"); else args+=(--register-unsafely-without-email); fi
    certbot "${args[@]}" || log 'ACME failed; resolve DNS/port 80 and rerun this script.'
  fi
  if has_tls; then install_nginx "$SCRIPT_DIR/pharmascope.nginx.conf"; fi
fi
systemctl is-active --quiet pharmascope-api.service pharmascope-worker.service || die 'A PharmaScope service failed.'
if has_tls; then
  "$SCRIPT_DIR/verify.sh" "https://$DOMAIN" "http://127.0.0.1:$API_PORT"
  log "Deployment verified: https://$DOMAIN ($RUNTIME_MODE)"
else
  die 'HTTP is available but TLS is not configured. This deployment is not release ready; fix ACME/DNS and rerun.'
fi
