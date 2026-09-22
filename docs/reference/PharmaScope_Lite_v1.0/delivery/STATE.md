# 实施状态

- 项目：PharmaScope Lite v1.0；日期：2026-09-22。
- 当前状态：DEMO_READY（本地 replay 后端 + Next 静态前端）；不是V1_RELEASE_READY。
- 已交付：完整产品/工程文档、机器合同、SQL参考、虚构fixtures、目标部署模板、离线交互原型、静态检查和27组原型DOM检查。
- 已实现：FastAPI 合同 API、fixture replay 状态、HttpOnly 会话/CSRF/RBAC、证据与快照链、研究 SSE、审核发布、订阅投递 API，以及 Next.js 静态前端和根目录 design.md。
- 未完成：GPT Researcher live upstream 锁定与真实模型探针、PostgreSQL/Alembic 持久化、真实来源 contract test、SMTP 外发、4核8GB压测。
- 下一步：完成 M0 live 上游探针和 M6 集成验收；不直接把compose.target.yaml当成已构建镜像运行。
- 模式：当前原型只有DEMO/REPLAY；正式live必须显式配置并独立验收。
- 浏览器检查限定：set_content离线DOM；未验证file URL策略与持久化；正式E2E仍未运行。
