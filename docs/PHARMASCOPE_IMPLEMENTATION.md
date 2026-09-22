# PharmaScope Lite 实现说明

本仓库现在包含一个独立的 PharmaScope Lite API 和 Next.js 静态前端。原有 GPT Researcher API 仍可通过 `PHARMA_LEGACY=1` 启动；默认启动的是 PharmaScope API。

## 本地启动

```bash
make setup
make dev
```

API 默认监听 `http://localhost:8000`。前端开发服务器在另一个终端运行：

```bash
cd frontend/nextjs
npm run dev
```

生产构建使用 `output: "export"`，产物位于 `frontend/nextjs/out`，可由 Nginx 或其他静态服务器托管。前端通过 `NEXT_PUBLIC_PHARMA_API_URL` 和 `NEXT_PUBLIC_PHARMA_WORKSPACE_ID` 指定 API 与工作区。

DEMO 回放使用文档中的虚构 fixture，登录示例账号为 `analyst@pharmascope.invalid`，密码为 `demo`。该密码只用于本地回放，不得配置到 live 环境。API 使用 HttpOnly 会话 Cookie、CSRF token、workspace membership 和服务端角色校验；跨 workspace 对象按 404 隐藏。

## 验证

```bash
make test
make test-e2e
make seed-demo
make verify-docs
```

后端的 `backend/pharma_scope_app.py` 实现了合同中的 59 个路径，包括药物与别名、来源同步任务、试验/文献、快照观察和差异、证据、研究运行与 SSE、报告版本审核发布、订阅、收件箱和审计。DEMO 模式只使用 replay fixture；真实 ClinicalTrials.gov、PubMed 和 GPT Researcher live 运行仍需显式配置来源凭据、模型凭据和 worker 适配器，失败不会回退到 DEMO。

前端页面遵循根目录 `design.md`，详情页采用静态导出兼容的固定路径加 `?id=`，API 不可用时显示明确的 DEMO fallback 标识。
