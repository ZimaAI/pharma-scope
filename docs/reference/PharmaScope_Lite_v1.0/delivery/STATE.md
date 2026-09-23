# 实施状态

- 日期：2026-09-23；状态：**V1_RELEASE_BLOCKED_EXTERNAL**。不能更新为 `V1_RELEASE_READY`，真实模型成功、PubMed 网络验收和最新公网部署仍有外部阻塞。
- 依据：[测试记录](TEST_RESULTS.md)、[机器证据](v1-verification.json)、[最终后端输出](v1-tests.txt)。本轮保留原有未提交改动并在其上继续实现；没有将先前 checkpoint/原型结果视为 V1 完成。

| 阶段 | 当前实现与实际验收 |
|---|---|
| M0 | GPTR 0.14.7 / 完整 commit 锁定，79 项运行依赖精确锁；独立新 venv 安装、import、pip check 通过。真实 GPTR 生命周期及 SDK 合同、预算、取消、恢复通过；真实付费模型调用未成功执行（缺配置）。 |
| M1 | PostgreSQL 16 + SQLAlchemy 按对象 repository + Alembic；外键/索引/唯一约束/事务、scrypt、workspace/RBAC/CSRF/审计/幂等、持久会话和运行模式隔离。迁移往返、双进程并发、API 重启持久化、备份恢复实测通过。 |
| M2 | CT.gov v2 和 PubMed ESearch/EFetch 适配器、超时/限流/重试、原始快照、hash、日期精度、观察链/回滚/变化/证据。真实 CT.gov → API → worker → PostgreSQL 成功；PubMed 缺身份配置，明确失败/部分完成。 |
| M3 | 真实 GPTResearcher 中注入单一受限工具循环；按已审批关联/workspace/来源/观察窗口取证；调用/记录/token/总时间预算，持久消息断点、取消、重试、SSE。live 无 fixture fallback；模型配置失败保留原因与步骤，不生成伪报告。 |
| M4 | 不可变版本/hash/claim-evidence 校验，作者/发起人自审禁令、退回/批准/发布、站内通知；每日/每周/IANA 时区、持久 occurrence、投递去重、SMTP dry-run/失败重试。实际外发默认关闭，未验证真实邮件投递。 |
| M5 | 正式 Next.js 22 路由静态导出；无静态业务 fallback，API 确认模式；replay Chromium 18 项、真实 live PostgreSQL+CT.gov Chromium 8 项通过。 |
| M6 | 独立 Compose/systemd/Nginx/worker/数据库配置、幂等安装、备份和运维入口；真实独立 Nginx TLS/redirect/static/API/SSE、健康检查通过。Docker 构建及最新系统安装因权限未执行。 |

最新总测：`PHARMA_TEST_DATABASE_URL=<独立测试库> make test` **82 passed，0 skipped**，其中 6 项真实 PostgreSQL；`make test-e2e`、`make verify-docs`、生产 build 已通过。30 秒/6 并发小规模探针 773 请求、0 错误，196 写入全部可见；不代表容量或长期稳定性验收。

外部阻塞：

1. 提供真实 `OPENAI_API_KEY`、兼容 endpoint 与模型名，执行实际模型探针及完整 live 报告审核闭环。
2. 提供真实 `NCBI_EMAIL`（API key 可选），验证 PubMed 网络成功及覆盖。
3. 生产 PostgreSQL 专用连接、管理员初始化和主机 sudo/root 或 Docker 权限，用于安装最新服务/Nginx；不能复用临时测试库作生产。
4. 真实 SMTP 是可选外发集成；需要服务凭据及明确开关。当前保持禁发，不能声称真实邮件成功。

公网 `https://pharmascope.zimagent.top` 的现有 **旧 replay** 页面和 health 可访问，HTTP→HTTPS 正常；`/readyz` 仍为旧配置的 404。本轮没有部署新公网版本、修改其他项目 Nginx block 或重启其他项目。已有 API 使用 `127.0.0.1:18180`；Compose 模板独立使用 `18181`；隔离 PG 测试使用 `18432`，临时 API/worker/Nginx 与测试 schema 已清理，测试 PostgreSQL 已停止（数据目录保留供复验）。

已知边界：repository 仍按请求装载领域集合，尚未做大规模 SQL 分页改造；没有长期 soak 或 4核8GB 容量验收。模型工具仅搜索/读取授权持久证据，来源发现和候选关联审批先行，不提供任意网页自治检索。LLM/SMTP 不承诺 exactly-once。原 Gherkin 文件仍是规格，已执行 pytest/浏览器测试才是实现证据。
