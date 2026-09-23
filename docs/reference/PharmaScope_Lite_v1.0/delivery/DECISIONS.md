# 已记录决策

D-001 基于GPT Researcher，不使用DeerFlow。
D-002 4核8GB、外部模型、1研究槽、2外部请求并发、无子Agent。
D-003 Next静态导出，Nginx/API/Worker/PG，非微服务。
D-004 Fork内部领域Conductor；MCP/额外Agent框架不进入V1。
D-005 项目检查点，不声称上游有无损resume。
D-006 本包交付原型与规格，真实后端及压测未实现。


## 2026-09-23 中断续做后的实现决策

- 用户已明确授权完整端到端实施及目标域名部署，按 end-to-end 执行；旧包的阶段确认或默认不部署条款不要求再次询问。没有系统权限/外部凭据的步骤独立记录阻塞。
- 旧整份 JSON checkpoint 仅保留升级导入；当前业务对象进入独立 SQLAlchemy 表。API 短事务与 worker 写入合并、不可变历史和 PostgreSQL 单执行槽共同约束并发。序号竞争在数据库事务中重新分配，不能覆盖取消事件。
- GPT Researcher 固定原始提交 `8da8d8f85d7124649bb059ce1b2106ed3d3f5ea5`，最小 Lite factory 注入补丁见根目录 `patches/README.md`。不使用上游默认开放网页/embedding/MCP 路径。运行依赖由 `backend/requirements-runtime.lock` 精确锁定，已在独立环境安装验证。
- 模型实际工具为 `search_evidence` 和 `read_evidence`；真实来源 discovery/refresh 由持久 source-sync worker 执行，药物候选关联人工审批后才能进研究。旧工具清单中的未实现工具已移除，避免宣称具备任意联网研究能力。
- 时间窗口按成功 observation 的 fetched_at 选择 snapshot，包括复用历史内容的回滚观察；不把抓取时间解释成临床事件时间。
- API 合同新增 live runtime、实际 usage/任务状态、来源健康检查和投递重试；保留严格 JSON Schema。正式前端两种模式都使用 API，删除静态 fallback 和旧 PWA 认证缓存。
- 公网现有部署保持原样，最新 Nginx/TLS/SSE 在独立实例验证；没有 sudo/Docker 权限时不绕过主机管理边界，也不把本地代理检查等同于公网升级。
