# 交付验证记录

日期：2026-09-22。已补充本地 replay 后端与 Next 静态前端；live 来源、模型和数据库仍未启用。

| 测试层 | 状态 | 证据及限定 |
|---|---|---|
| 文档JSON/引用/字段合同/样例hash | 已执行 | CONTEXT_VALIDATION.md；是子集检查，不是完整OpenAPI认证 |
| 原型JavaScript语法 | 已执行通过 | 提取inline脚本后运行node --check；不包含正式前端构建 |
| 原型浏览器离线DOM | 27组通过 | prototype-tests.json；Playwright set_content，未访问外部服务 |
| 原型关键布局 | 已执行通过 | 1440/1024/390宽度；previews截图；表格小屏局部滚动 |
| 浏览器本地存储/file://策略 | NOT_RUN | 当前浏览器环境禁用URL导航，未验证持久存储与本地打开策略 |
| 后端单元 / 正式前后端E2E | 已执行（离线） | `/tmp/pharmavenv/bin/pytest -q backend/tests/test_pharma_scope_api.py`：4 passed；覆盖健康检查、登录、workspace 隔离、CSRF、药物/试验/快照/diff、研究运行与 SSE；真实浏览器联调仍未执行 |
| Next 静态前端构建 | 已执行通过 | `cd frontend/nextjs && npm run build`；静态预渲染 21 个页面，未运行生产 Node 服务 |
| 文档合同复核 | 已执行通过 | `python docs/reference/PharmaScope_Lite_v1.0/scripts/verify_context.py`（PyYAML/jsonschema 已安装）：JSON、68 个 OpenAPI 操作、Schema、fixtures、SQL 引用和 26 个验收场景检查通过 |
| 数据库迁移与SQL执行 | NOT_RUN | schema.sql仅结构参考，静态目标引用检查不等于建表成功 |
| GPT Researcher固定SHA及模型 | NOT_RUN | upstream.lock.json尚未锁定，M0必须实际验证 |
| CT.gov / PubMed真实接口 | NOT_RUN | 已核对官方文档，未执行来源contract test |
| SMTP / 真实推送 | NOT_RUN | 没有向真实用户发送信息 |
| 4核8GB峰值内存与长时稳定性 | NOT_RUN | 资源限制是设计起点，不是实测保证 |

重新执行文档检查：`python scripts/verify_context.py`。原型检查：`python prototype/smoke_test.py`。两者只操作本机文件/浏览器，不代表产品完成。
实施者随后追加：测试ID、日期、Git SHA、依赖锁、机器规格、完整命令、退出码、证据文件和失败/跳过原因。不得把此处原型回放的0模型调用记为产品成本优化成果。
