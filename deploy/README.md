# PharmaScope Lite 部署

两种入口使用同一 PostgreSQL repository、独立 worker 和 Next.js 静态导出。当前主机的其他项目占用 80/443、5432 和 18080；不要停止它们。PharmaScope systemd API 使用 `127.0.0.1:18180`，Compose web 默认使用 `127.0.0.1:18181`。部署脚本只操作 PharmaScope 的 unit、目录和 Nginx site；Nginx 通过 reload 保留其他站点。

## Compose

配置文件必须在所有命令中保持一致。`compose.sh` 同时传递 Compose 插值文件和容器 env_file，避免 live 命令误装载 demo 环境。

```bash
cp .env.example.demo .env.demo
chmod 600 .env.demo
# live 使用 .env.example.live 的私有副本，填写真实 PostgreSQL、模型和 NCBI 配置。
bash deploy/compose.sh .env.demo build
bash deploy/compose.sh .env.demo run --rm migrate
bash deploy/compose.sh .env.demo run --rm api python -m backend.cli seed-demo
bash deploy/compose.sh .env.demo up -d db api worker web
curl -fsS http://127.0.0.1:18181/readyz
bash deploy/compose.sh .env.demo logs --tail=100 api worker db web
```

上面的 seed-demo 仅用于全新的 replay 数据库；已初始化数据库会明确拒绝重置。live 首次迁移后，以交互密码创建管理员：

```bash
bash deploy/compose.sh /private/pharmascope.env run --rm api python -m backend.cli init \
  --email admin@example.org --display-name 管理员 --workspace-name 研发中心
# 以输出的 workspace UUID 添加独立审核者，禁止作者审核自身报告。
bash deploy/compose.sh /private/pharmascope.env run --rm api python -m backend.cli add-user \
  --email reviewer@example.org --role reviewer --workspace-id ACTUAL_WORKSPACE_UUID
bash deploy/compose.sh /private/pharmascope.env up -d db api worker web
```

Compose 内部数据库主机名为 `db`；`POSTGRES_PASSWORD` 和 URL 中的密码必须一致，URL 特殊字符需百分号编码。数据库端口不映射宿主机。四组件具有各自健康检查、重启策略、资源限制和日志轮转。API healthcheck 请求 `/readyz`，worker healthcheck 检查数据库 heartbeat。单独管理组件：

```bash
bash deploy/compose.sh /private/pharmascope.env stop worker
bash deploy/compose.sh /private/pharmascope.env start worker
bash deploy/compose.sh /private/pharmascope.env logs -f worker
```

`down` 保留 PostgreSQL volume；不要对生产运行 `down -v`。切换 replay/live 必须使用隔离数据库，不能把演示库作为 live 数据源。

## 现有主机上的 systemd + Nginx

先准备专属 PostgreSQL 数据库和账号。可以使用 Compose 的独立 `db`，但 systemd 连接时必须为它增加仅 loopback 的独立端口；也可由管理员提供独立 PostgreSQL 实例。不要修改已存在的 5432 实例配置或其他项目数据库。环境示例中的 `db` 主机名只适用于 Compose。

```bash
make setup
sudo install -d -m 0750 /etc/pharmascope
sudo install -m 0600 .env.example.live /etc/pharmascope/pharmascope.env
sudoedit /etc/pharmascope/pharmascope.env
# 设置实际数据库连接；检查模型 key、PHARMA_MODEL、NCBI_EMAIL。
sudo PHARMA_ENV_FILE=/etc/pharmascope/pharmascope.env bash deploy/install.sh --check
sudo PHARMA_ENV_FILE=/etc/pharmascope/pharmascope.env bash deploy/install.sh
```

安装到公网域名时，replay/live 都必须配置 `PHARMA_PUBLIC_ORIGIN=https://pharmascope.zimagent.top`、`PHARMA_COOKIE_SECURE=1` 和对应同源 CORS；脚本会拒绝本地 HTTP 配置。

脚本不覆盖环境文件。它先构建同源静态前端、备份数据库、执行 migration，再更新本项目 API/worker、验证 ready、切换带版本的静态目录。已有 TLS 证书时直接使用 HTTPS 配置。Nginx 校验失败时恢复本项目原配置并停止，不 reload 错误配置。脚本使用锁防止重叠执行，可重复执行升级。

首次 live 部署需在迁移后创建账号。可先使用同一私有配置执行迁移/初始化，之后运行安装脚本：

```bash
sudo .venv/bin/python deploy/env-run.py /etc/pharmascope/pharmascope.env .venv/bin/alembic upgrade head
sudo .venv/bin/python deploy/env-run.py /etc/pharmascope/pharmascope.env .venv/bin/python -m backend.cli init \
  --email admin@example.org --workspace-name 研发中心
```

TLS 需要域名 DNS 指向本机、80/443 可达以及 root 操作；脚本使用 certbot webroot。ACME 失败会保留 HTTP 并以失败状态结束，不声称 HTTPS 已部署。现有证书续期仍由主机 certbot timer 管理，使用 `systemctl list-timers '*certbot*'` 检查。

```bash
systemctl status pharmascope-api.service pharmascope-worker.service
journalctl -u pharmascope-api.service -u pharmascope-worker.service -n 100 --no-pager
bash deploy/verify.sh
```

`verify.sh` 检查真实 API/公网 health、ready、静态入口、401/request id 和 HTTPS 跳转。提供 `PHARMA_VERIFY_COOKIE_FILE`（私有 curl cookie jar）与 `PHARMA_VERIFY_SSE_PATH=/api/v1/workspaces/.../research/runs/.../events` 后还验证已存在任务的认证 SSE。没有这两个参数时 SSE 标记 NOT_RUN，不伪造通过。

## 不需要 root 的验证

```bash
bash deploy/test-postgres.sh start
bash scripts/test_postgres.sh
# 需一个已经运行的 replay API（默认18180），正式静态构建需先存在。
.venv/bin/python deploy/proxy-smoke.py
```

测试 PostgreSQL 只监听 `127.0.0.1:18432`，目录 `/tmp/pharmascope-v1-pg-$USER` 为 0700，trust 仅用于隔离的本机测试，不能用于生产。集成测试自动创建并清理独立 schema，不删除现有表。`test-postgres.sh start` 可重复执行；`stop` 只停止该独立实例。代理测试使用临时 TLS 证书、18480/18443 临时端口，校验真实 Nginx、HTTPS 跳转、静态 JS、API 认证与 SSE，然后退出；不修改系统 Nginx。

详细迁移、备份与限制见 [运维手册](../docs/PHARMASCOPE_OPERATIONS.md)。
