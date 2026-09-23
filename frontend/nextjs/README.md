# PharmaScope Lite 前端

Next.js 14 静态导出工作台。两种运行模式都使用真实 HTTP API 和 Cookie 会话；前端不保存 demo 数组，也不会在 API 失败时返回演示数据。

## 构建

```bash
npm --prefix frontend/nextjs install --legacy-peer-deps
NEXT_PUBLIC_PHARMA_API_URL='' npm --prefix frontend/nextjs run build
```

产物位于 `frontend/nextjs/out`。生产环境由独立 Nginx 提供静态文件，`/api/`、`/healthz`、`/readyz` 反代到 PharmaScope API。浏览器默认同源，构建不写入 `localhost:8000`。`NEXT_PUBLIC_PHARMA_API_URL` 仅在明确需要跨域开发时指定。

模式由 `/healthz` 与 `/api/v1/auth/me` 返回的 `runtime_mode` 确认。`NEXT_PUBLIC_PHARMA_RUNTIME_MODE=replay` 只是初始界面配置，无法把 live API 转成演示数据。replay 的虚构数据在演示 API 服务端加载；live 接口失败只显示错误。

不再注册离线 PWA worker，避免会话和工作区业务数据被旧缓存复用。`public/sw.js` 会退役已有安装的旧 worker。

## 已联调功能

- 登录、登出、CSRF、工作区切换与成员角色管理。
- 药物建档与筛选、试验和文献投影、观察历史、原始快照、事件修订和证据抽屉。
- 来源同步、任务轮询、候选药物关联的确认 / 拒绝 / 撤销。
- 研究范围、来源和预算；命名 SSE 事件、Last-Event-ID 恢复、断线重连、取消和重试。
- 完整报告正文、版本 / hash、证据、修订、独立审核、退回和发布。
- 每日 / 每周订阅、IANA 时区预览、暂停、立即调度、投递记录和站内通知。
- 401 / 403 / 404 / 409 / 422 / 5xx 与 request ID，加载及空状态。

研究候选关联需要 reviewer / admin 在「工作区与关联审核」确认后，才能作为 live 研究证据。真实模型、SMTP 和来源密钥仅配置在服务端，不进入浏览器。

## 浏览器验证

```bash
.venv/bin/python -m playwright install chromium
npm --prefix frontend/nextjs run build
.venv/bin/python scripts/test_frontend_e2e.py
```

脚本启动独立临时端口的真实 replay API，使用 Chromium 验证生产静态导出。登录、CSRF、创建、研究、SSE、版本、审核、订阅、来源任务与工作区均请求实际 API；只有错误展示测试注入明确的失败响应。脚本不调用真实模型或邮件，也不将 replay 结果当成 live 验证。结果写入 `outputs/frontend-e2e-results.json`，测试 API 自动清理。

完整 PostgreSQL / worker / Nginx 运维参见 [项目运维说明](../../docs/PHARMASCOPE_OPERATIONS.md)。

真实来源的 LIVE 浏览器检查单独执行（需要独立测试 PostgreSQL 和外网）：

```bash
PHARMA_TEST_DATABASE_URL=postgresql+psycopg://pharma_test@127.0.0.1:18432/pharmascope_test \
  .venv/bin/python scripts/test_live_frontend.py
```

该脚本创建随机 schema、CLI 账号、live API 和独立 worker，真实同步一条 ClinicalTrials.gov 记录，浏览器验证 LIVE 标签、NCT 记录、观察 / 快照 / hash、来源部分完成和候选关联审核。它显式移除测试子进程中的 NCBI 与模型凭据，验证缺少身份和模型配置时的真实失败状态，不生成成功的模型结果。结束后清理 schema 与进程；证据位于 `outputs/live-frontend-results.json` 与 `outputs/live-browser-*.png`。来源任务可通过 `/settings?job_id=...` 在刷新后重新查看。
