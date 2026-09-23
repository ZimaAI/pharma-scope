# V1 实测记录

执行日期：2026-09-23；Python 3.12.3，PostgreSQL 16，Chromium/Playwright，正式 Next.js 静态导出。这里仅记录已实际执行的结果。机器证据见 [v1-verification.json](v1-verification.json)，后端最终输出见 [v1-tests.txt](v1-tests.txt)。

| 命令/检查 | 结果 | 边界 |
|---|---|---|
| `PHARMA_TEST_DATABASE_URL=postgresql+psycopg://pharma_test@127.0.0.1:18432/pharmascope_test make test` | 82 passed，0 skipped，退出 0，37.67 秒 | 含 6 项真实 PG 集成；其他来源/模型网络合同使用明确 MockTransport |
| `make test-e2e` | 构建通过；正式 Chromium 18 项通过 | 真实 replay API，非 prototype smoke |
| `npm --prefix frontend/nextjs run build` | 22 静态路由通过，lint/type 通过 | 浏览器 JS 无 localhost:8000 |
| `PHARMA_TEST_DATABASE_URL=<独立库> .venv/bin/python scripts/test_live_frontend.py` | 8 项通过 | 真实 live PG/CT.gov/浏览器；PubMed/模型缺配置的错误明确可见，未宣称外部模型成功 |
| `make verify-docs` | 通过，70 个操作/引用/Schema/fixtures/文档检查 | 不冒充执行原 Gherkin 或参考 DDL |
| `make test-proxy` | 真实独立 Nginx TLS、HTTPS redirect、static HTML/JS、health/ready、401 和认证 SSE 通过 | 使用临时受信任测试证书，不等同于公网更新 |
| `make dev` | loopback:8000 明确 replay 启动和 health 通过，随后停止 | 临时内存 demo，无持久化宣称 |
| `alembic upgrade head`、重复 upgrade、downgrade base、再次 upgrade | 独立 PG schema 中通过 | 生产不自动执行 downgrade |
| 两个 API 进程并发写入、停止/重新启动 API | 18 并发写入无丢失；记录/会话/审计重启保留 | 与运行中的其他数据库/项目隔离 |
| worker 独立进程、heartbeat、任务、SSE Last-Event-ID、取消 | 通过 | 缺模型配置的 live 任务明确失败；未生成报告 |
| `deploy/backup.py` + 隔离库 `pg_restore` | custom dump 与恢复对象校验通过 | dump 0600，无密码出现在命令参数 |
| `.venv/bin/python scripts/load_smoke.py`（配置独立 PG） | 30.260 秒，6 并发，773 请求，0 错误，196/196 写入保留 | 25.55 req/s，p95 336.46 ms，峰值 RSS 80.91 MiB；小规模探针 |
| 新独立 venv 安装 `backend/requirements-runtime.lock`、`pip check`、源/研究测试 | 79 依赖安装/检查通过，21 项验证通过 | GPTR 真实 import/lifecycle；网络响应是明确合同模拟 |
| `npm ... ci --dry-run --ignore-scripts --legacy-peer-deps` | 通过 | 锁文件与 package.json 一致；正式 build 已执行 |
| `make compose-config`；live Compose config；`install.sh --check` | 通过 | 未获 Docker socket/root 权限，未构建/启动镜像 |
| shell/Python 编译、systemd unit verify、`git diff --check` | 通过 | 只校验本项目文件 |
| `bash deploy/verify.sh` | **退出 22：公网 ready 404**；直连 health/ready、公网 health 通过 | 旧系统 Nginx 需要管理员安装新配置 |

真实 CT.gov 抓取并持久化了 `NCT03625323`。原始内容 SHA-256 为 `2107cefda997cbb66403043f4f59b6b6f5a99ffc4469650d63cfe5e9309ed4a3`；来源更新时间 `2026-04-22`，精度为 day。该日期不是本轮抓取时间。请求限制 1 条产生 truncated/partial，PubMed 缺 `NCBI_EMAIL` 产生 failed，未解释成无结果。

真实外部探针 `python -m backend.live_probe --sources --model` 返回非零：GPTR import 与 CT.gov PASS，PubMed `configuration`、模型 `model_credentials_missing`。live 浏览器研究同样显示 `MODEL_CONFIGURATION_ERROR`、`report_id=null`、`model_calls=0`。这属于缺配置行为验证，**不是模型成功验收**。

本轮还修复并加入回归：并发事件覆盖取消事件、取消后迟到报告提交、角色撤销后仍执行模型、刷新第二条失败丢失第一条结果、单条订阅阻塞 worker、SMTP 发送期间失租继续运行、无效 schedule、冻结订阅范围、作者自审、旧版本发布、跨 workspace 引用和 reader 草稿导出。

NOT_RUN / BLOCKED：真实 PubMed 成功、真实模型成功、真实 SMTP 外发、Docker image build/run、最新公网系统安装、长期稳定性/完整容量验收。其余主机服务和 7 个 Nginx site 保留；没有把 demo/replay 或 MockTransport 结果列作 live 成功。
