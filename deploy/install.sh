#!/usr/bin/env bash
set -Eeuo pipefail

DOMAIN="pharmascope.zimagent.top"
API_PORT="18180"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
TARGET_USER="${SUDO_USER:-$(stat -c '%U' "$REPO_ROOT")}"
WEB_ROOT="/var/www/pharmascope/current"
ACME_ROOT="/var/www/pharmascope-acme"
NGINX_SITE="/etc/nginx/sites-available/pharmascope"
NGINX_LINK="/etc/nginx/sites-enabled/pharmascope"
SYSTEM_UNIT="/etc/systemd/system/pharmascope-api.service"

log() { printf '\n==> %s\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

if [[ "${EUID}" -ne 0 ]]; then
  exec sudo bash "$0" "$@"
fi

id -u "$TARGET_USER" >/dev/null 2>&1 || die "找不到部署用户: ${TARGET_USER}"
TARGET_UID="$(id -u "$TARGET_USER")"

log "检查端口 ${API_PORT}"
if ss -ltn "sport = :${API_PORT}" | tail -n +2 | grep -q LISTEN; then
  if ! pgrep -af "uvicorn.*backend\.pharma_scope_app:app.*--port ${API_PORT}" >/dev/null; then
    die "端口 ${API_PORT} 已被其他进程占用，为避免影响现有项目，部署已停止。"
  fi
fi

log "构建前端"
runuser -u "$TARGET_USER" -- bash -lc "
  set -Eeuo pipefail
  cd '$REPO_ROOT'
  if [[ -s \"\$HOME/.nvm/nvm.sh\" ]]; then . \"\$HOME/.nvm/nvm.sh\"; fi
  command -v npm >/dev/null || { echo '找不到 npm' >&2; exit 1; }
  NEXT_PUBLIC_PHARMA_API_URL='https://${DOMAIN}' \\
  NEXT_PUBLIC_PHARMA_WORKSPACE_ID='dee59b72-2cb2-5255-934c-b44a3fd8911c' \\
  npm --prefix frontend/nextjs run build
"

log "安装静态前端"
install -d -o root -g root "$WEB_ROOT" "$ACME_ROOT"
rm -rf "${WEB_ROOT}.new"
install -d -o root -g root "${WEB_ROOT}.new"
cp -a "$REPO_ROOT/frontend/nextjs/out/." "${WEB_ROOT}.new/"
rm -rf "$WEB_ROOT"
mv "${WEB_ROOT}.new" "$WEB_ROOT"

log "切换 API 为 systemd 服务"
if [[ -S "/run/user/${TARGET_UID}/bus" ]]; then
  runuser -u "$TARGET_USER" -- env \
    XDG_RUNTIME_DIR="/run/user/${TARGET_UID}" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${TARGET_UID}/bus" \
    systemctl --user disable --now pharmascope-api.service >/dev/null 2>&1 || true
fi

install -m 0644 "$REPO_ROOT/deploy/pharmascope-api.service" "$SYSTEM_UNIT"
sed -i \
  -e "s#^User=.*#User=${TARGET_USER}#" \
  -e "s#^Group=.*#Group=${TARGET_USER}#" \
  -e "s#^WorkingDirectory=.*#WorkingDirectory=${REPO_ROOT}#" \
  -e "s#^ExecStart=.*#ExecStart=${REPO_ROOT}/.venv/bin/uvicorn backend.pharma_scope_app:app --host 127.0.0.1 --port ${API_PORT} --workers 1#" \
  "$SYSTEM_UNIT"
systemctl daemon-reload
systemctl enable --now pharmascope-api.service

log "安装临时 HTTP Nginx 配置"
install -m 0644 "$REPO_ROOT/deploy/pharmascope.nginx.initial.conf" "$NGINX_SITE"
ln -sfn "$NGINX_SITE" "$NGINX_LINK"
nginx -t
systemctl reload nginx

if [[ ! -s "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" || ! -s "/etc/letsencrypt/live/${DOMAIN}/privkey.pem" ]]; then
  log "申请 TLS 证书"
  certbot certonly --webroot -w "$ACME_ROOT" -d "$DOMAIN" \
    --non-interactive --agree-tos --register-unsafely-without-email
fi

log "切换最终 HTTPS Nginx 配置"
install -m 0644 "$REPO_ROOT/deploy/pharmascope.nginx.conf" "$NGINX_SITE"
nginx -t
systemctl reload nginx

log "验证部署"
systemctl is-active --quiet pharmascope-api.service || die "API 服务未运行"
curl --fail --silent --show-error "http://127.0.0.1:${API_PORT}/healthz"
printf '\n'
curl --fail --silent --show-error "https://${DOMAIN}/healthz"
printf '\n\nPharmaScope 已部署: https://${DOMAIN}\n'
