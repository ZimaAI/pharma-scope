# PharmaScope Lite 实现说明

当前实现及验收以 [STATE.md](reference/PharmaScope_Lite_v1.0/delivery/STATE.md) 和 [TEST_RESULTS.md](reference/PharmaScope_Lite_v1.0/delivery/TEST_RESULTS.md) 为准。上次中断留下的 checkpoint、原型 smoke 和模式变量不足以证明 live 完成；本轮已替换这些关键路径并执行正式验证。

## 运行方式

```bash
make setup
make dev                         # 明确 replay，只绑定本机；无数据库时仅供临时演示
# 单独启动 Next 开发服务器时配置同源代理或明确的开发 API origin。
# 持久化开发环境的完整命令见 PHARMASCOPE_OPERATIONS.md。
```

默认模式是 live，未配置 PostgreSQL 会明确不可就绪，不自动载入 fixtures。演示必须显式设置 `PHARMA_RUNTIME_MODE=replay`；临时内存演示的数据不保留。持久化 replay 与 live 必须使用独立数据库，数据库会记住运行模式并拒绝混用。

`.env.example.development`、`.env.example.test`、`.env.example.demo` 和 `.env.example.live` 分别描述开发、隔离测试、Compose 演示和生产。配置真实密钥的文件应保存在 Git 外，权限 0600。生产前端 API URL 为空，Nginx 提供同源 `/api/`。

## 实现边界

- `backend/db.py`、`repository.py`、Alembic：按业务对象持久化，外键/唯一约束/workspace 索引，短事务、幂等、审计、持久会话、不可变快照/版本。可从旧 checkpoint 导入，禁止演示库转换为 live。
- `backend/cli.py`：数据库初始化、管理员/成员创建及显式 demo seed。live 密码使用 scrypt；live 不接受 demo 密码或开发身份 Header。
- `backend/sources.py`、`source_ingest.py`：真实 ClinicalTrials.gov v2、PubMed ESearch/EFetch，超时/退避/速率限制、原始内容 hash、日期精度、重复/回滚观察、变化和证据。
- `backend/research.py`：通过锁定 GPT Researcher 的真实 `conduct_research`/`write_report` 生命周期执行单一受限工具循环。模型只能搜索/读取已审批药物关联及 workspace、来源、观察时间窗口内的持久化证据。来源同步和关联审批先于研究；没有任意网页/代码执行工具。
- `backend/worker.py`：独立 PostgreSQL 队列，部署单槽锁、租约/heartbeat、断点恢复、取消、每日/每周订阅与投递。取消/恢复保留使用量；不承诺远程 LLM 或 SMTP exactly-once。
- `backend/pharma_scope_app.py`：鉴权、CSRF、权限、真实持久任务、SSE 重连、报告版本/hash/审核/退回/发布、通知、订阅、来源设置和审计。
- `frontend/nextjs`：正式 React 页面始终调用认证 API；没有浏览器静态 demo 业务 fallback。模式由 API 确认，支持 workspace、证据快照、来源部分失败、关联审批、研究进度和报告审核。静态导出，无生产 Node 服务。

## 验证入口

```bash
make test
make test-postgres               # 独立 PG16；随机 schema 自动清理
make test-e2e                    # 生产构建 + 正式 Chromium + 真实 replay API
make test-proxy                  # 独立真实 Nginx/TLS/API/SSE；不改系统站点
make verify-docs
npm --prefix frontend/nextjs run build
# 外部 live 配置验证，缺凭据时明确返回非零，不伪造成功：
.venv/bin/python -m backend.live_probe --sources --model
```

离线模型/来源合同测试使用明确标记的 HTTP MockTransport，但真正实例化 GPT Researcher 和 SDK；它们不能替代真实模型验收。ClinicalTrials.gov 已实际完成 API → worker → PostgreSQL 同步。PubMed 网络验收和真实模型执行仍需部署者提供配置。

## 部署与剩余边界

完整操作见 [运维说明](PHARMASCOPE_OPERATIONS.md) 与 [部署说明](../deploy/README.md)。Compose 默认独立本机端口 `18181`；已有主机 systemd 部署沿用 PharmaScope 专用 `18180`。安装脚本不删除其他 Nginx server block，也不重启其他项目。

当前公网是旧 replay 部署，不能把它描述为本轮 V1 live 已上线。最新系统服务及 Nginx 安装受 root 权限阻塞，真实模型与 PubMed 配置也未提供。数据库 repository 仍按请求装载领域集合，适合本版小规模验证；大规模索引查询重构、4 核 8GB 容量与长时间稳定性尚未验收。SMTP 默认禁止真实外发。
