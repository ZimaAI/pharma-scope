# PharmaScope Lite 开发与运维

## 模式与数据库隔离

`PHARMA_RUNTIME_MODE=replay` 读取原创虚构 fixtures，供离线演示；`live` 读取 PostgreSQL 的实际业务记录，通过官方来源适配器和 GPT Researcher 执行研究。live 缺模型 key、来源身份、网络或数据库时必须给出配置/来源/任务失败，不会退回演示数据。`gptr` 不是 live 验收证据。

配置示例按用途拆开：`.env.example.development` 使用 `pharmascope_dev`；`.env.example.test` 使用独立测试库并在运行中创建临时 schema；`.env.example.live` 是生产模板；`.env.example.demo` 是 Compose 演示环境。真实密码保存在 Git 外。生产与演示必须使用不同数据库或不同实例。

## 游客和账号管理

公开首页进入登录页。游客登录创建独立的只读会话，只能读取管理员指定演示账号所属工作区的数据；该账号本人仍可用密码按其角色登录。管理员在“工作区”页面选择演示账号，也可以用 `python -m backend.cli set-demo --workspace-id <UUID> --email <账号邮箱>` 设置。演示账号必须属于目标工作区且处于启用状态。公开演示应使用专用工作区，确认其中的报告、证据和记录可以公开展示后再指定账号。

管理员可管理成员角色与启用状态，成员可以改自己的密码；改密、停用和演示账号切换应撤销相应的旧会话。浏览器隐藏游客写入控件，API 同时执行角色、游客只读、会话和 CSRF 检查。面向公网运行时保持 `PHARMA_ALLOW_DEV_HEADER=0`、安全 Cookie 和同源 HTTPS，不在 Git 或静态网页中存储账号密码。

## 本地开发

```bash
make setup
bash deploy/test-postgres.sh start
# 仅在首次创建开发库时执行：
/usr/lib/postgresql/16/bin/createdb -h 127.0.0.1 -p 18432 -U pharma_test pharmascope_dev
cp .env.example.development .env.development
chmod 600 .env.development
.venv/bin/python deploy/env-run.py .env.development .venv/bin/alembic upgrade head
.venv/bin/python deploy/env-run.py .env.development .venv/bin/python -m backend.cli seed-demo
.venv/bin/python deploy/env-run.py .env.development .venv/bin/uvicorn backend.pharma_scope_app:app --host 127.0.0.1 --port 18182
# 在另一终端启动同一数据库的 worker：
.venv/bin/python deploy/env-run.py .env.development .venv/bin/python -m backend.worker
```

开发库启动采用明确 replay 模式；改成 live 时需新建空库、执行 CLI init，并配置模型/来源。不得将现有 fixture 库直接改标为 live。`seed-demo` 拒绝覆盖已有数据。静态前端始终构建输出 `frontend/nextjs/out`，通过 Nginx 同源反代使用，不需要 Next.js 开发服务器。参考 [部署 README](../deploy/README.md) 中的 Compose 完整入口。

## 数据库迁移和升级

Alembic 是 PostgreSQL schema 入口，生产先执行 `alembic upgrade head`，不依赖 API 自动建表。`PHARMA_DATABASE_URL` 优先于兼容的 `DATABASE_URL`；请只维护一个值。数据库中保存 workspace、用户、会话、业务记录、不可变快照/报告、事件、审计、投递状态和 worker 租约。外键、唯一约束和 workspace 索引在迁移中创建。

升级顺序为“备份 → migration → API/worker 更新 → ready → 静态前端 → 验证”。安装脚本仅重启 `pharmascope-api` 和 `pharmascope-worker`，Nginx 使用 reload，不停止其他项目。数据库 downgrade 仅在隔离测试中验证；生产涉及不可逆数据时使用已验证的备份恢复策略，不盲目 downgrade。

```bash
.venv/bin/python deploy/env-run.py /private/pharmascope.env .venv/bin/python deploy/backup.py /private/backups
.venv/bin/python deploy/env-run.py /private/pharmascope.env .venv/bin/alembic upgrade head
# systemd 路径（需要管理员权限）：
sudo systemctl restart pharmascope-api.service pharmascope-worker.service
```

`backup.py` 将 PostgreSQL 密码通过子进程环境传递，不把 URL/密码写在 `pg_dump` 命令参数或日志中，并正确处理 `postgresql+psycopg://` URL。dump 采用 custom 格式，权限 0600。Compose 备份：

```bash
umask 077
bash deploy/compose.sh /private/pharmascope.env exec -T db \
  sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > /private/backups/pharmascope.dump
```

建议每天备份，保留至少 14 日并复制到独立故障域；备份盘应加密。恢复演练在空隔离库中执行 `pg_restore --exit-on-error --no-owner --dbname <连接信息> dump`，通过受保护 `PGPASSFILE` 提供密码。校验报告 hash、引用证据、审计、待处理任务和通知去重记录后再切换服务。不要自动删除已被报告引用的快照或审计；本版本没有自动保留期删除任务。

## 真实来源和模型配置

ClinicalTrials.gov v2 不需要 API key。PubMed 使用 `NCBI_EMAIL` 标识操作者，可选 `NCBI_API_KEY`；它不是终端用户邮箱。`PHARMA_SOURCE_TIMEOUT`、`PHARMA_SOURCE_RETRIES`、`PHARMA_SOURCE_MIN_INTERVAL` 控制超时、重试和速率。API 原始 payload、hash、来源更新时间、抓取时间和观察序号进入 PostgreSQL。429、超时或解析错误保留来源失败/部分完成，不能解释成零结果。

GPT Researcher 使用仓库锁定的真实上游源码。配置 `OPENAI_API_KEY`、`OPENAI_BASE_URL` 和 `PHARMA_MODEL`（也支持 `OPENAI_MODEL`）。兼容服务必须支持配置模型的 chat completion；设置一个模式变量不代表执行过模型。先使用很小预算的研究运行检查事件、工具调用、模型次数、报告证据和错误原因。预算由任务 request 中的 `budget` 控制，并受 `PH_MAX_TOOL_CALLS`、`PH_MAX_MODEL_CALLS`、`PH_MAX_RECORDS`、`PH_MAX_TOKENS`、`PH_MAX_SECONDS` 服务端上限约束。API 和 worker 目前使用同一受限环境文件，不能声称只有 worker 能读取模型 key；宿主机配置应只允许部署账号/管理员读取。

SMTP 默认 `PH_REAL_EMAIL_ENABLED=false`、`PH_SMTP_DRY_RUN=true`。开启 dry-run 测试可显式设 `PH_REAL_EMAIL_ENABLED=true` 并配置测试 sender/host，但保持 dry-run=true；只有两个开关同时允许外发才连接 SMTP。生产外发需要运营者配置真实凭据并明确启用。SMTP 不能保证 exactly-once，网络断开时需核对实际服务器结果。

## 健康检查、日志和故障处理

`/healthz` 检查 API 存活；`/readyz` 检查数据库准备情况，不触发付费模型或来源请求。worker 独立健康检查为 `python -m backend.worker --healthcheck`，读取数据库 heartbeat。来源健康和任务中的错误比进程存活更具体；ready 通过不等于所有外部供应商已真实调用通过。

日志使用 `journalctl -u pharmascope-api -u pharmascope-worker` 或 Compose logs；Nginx 独立日志位于 `/var/log/nginx/pharmascope.access.log`、`pharmascope.error.log`。诊断使用 request_id/run_id，不打印密码、完整环境变量、Cookie 或带 NCBI key 的请求 URL。

- 401/403：检查会话、CSRF、workspace membership 和角色；生产不要打开开发身份 Header。
- 数据库不可用/迁移缺失：检查专属 DB、连接 URL、迁移版本和磁盘；不要临时切回内存。
- 任务停滞：查看 worker 日志和 heartbeat，确认只有一个持有租约的执行 worker；恢复保留已有事件与失败原因。
- SSE 断线：带 Last-Event-ID 重连；Nginx 关闭 buffering/cache，90 秒超时。断开页面不会取消任务。
- 公网 ready 404 但本地 ready 正常：安装新 PharmaScope Nginx site 并 `nginx -t` 后 reload。
- 模型缺 key/模型名错误：研究任务明确失败，填写私有配置并重启本项目 worker，不回放 fixture。

## 验证和当前部署限制

`make test`、`make test-e2e`、`make verify-docs`、生产构建和 `bash scripts/test_postgres.sh` 是不同验证层；原型 screenshot 不能替代正式 E2E。`deploy/proxy-smoke.py` 验证独立真实 Nginx/TLS/静态资源/认证 SSE，但不能替代公网配置安装。

系统级安装需要管理员执行 `deploy/install.sh`，它会备份数据库、迁移、重启本项目服务并切换带版本的前端目录。无免密码 sudo 或 Docker socket 权限的开发账号仍可执行测试和只读部署检查，但不能替代系统级安装。完成安装后运行 `deploy/verify.sh` 和 `deploy/verify-guest.py`，分别确认站点与游客读写权限。没有真实模型 key 和 SMTP 凭据时，不能声称 live 模型成功或真实邮件已投递。

本版本 repository 按请求装载集合；虽然 PostgreSQL 对象独立行、事务与并发写已验证，大数据量下的分页/查询下推优化尚未完成。30 秒小规模负载探针只用于发现明显错误，不能视作 4 核/8 GB 生产容量或长时间稳定性验收。

可重复执行小规模探针：`PHARMA_TEST_DATABASE_URL=postgresql+psycopg://pharma_test@127.0.0.1:18432/pharmascope_test .venv/bin/python scripts/load_smoke.py`。默认 30 秒、6 并发、读写混合，创建独立 schema 并在结束后清理，结果写入 `outputs/verification/load-smoke.json`。不要把测试 URL 指向生产库。
