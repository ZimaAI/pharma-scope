# 16｜一手来源、核验范围与资料记录

核对日期2026-09-22。本包的业务规则、接口、部署预算和验收目标是项目设计，不代表上游已经提供或已经实测。以下URL供开发核对，开发时还需将具体提交/快照锁定。

| 编号 | 一手来源 | 本次使用与核验范围 |
|---|---|---|
| S01 | https://github.com/assafelovic/gpt-researcher | 已读README：Python应用、研究与写作、轻量前端、许可证；未部署 |
| S02 | https://raw.githubusercontent.com/assafelovic/gpt-researcher/main/gpt_researcher/agent.py | 已读类签名、ResearchConductor调用、ReportGenerator、cost语义；main不是固定锁 |
| S03 | https://raw.githubusercontent.com/assafelovic/gpt-researcher/main/gpt_researcher/config/variables/default.py | 已读模型/Embedding与默认并发；项目PH_开关不属于上游 |
| S04 | https://docs.gptr.dev/docs/gpt-researcher/retrievers/mcp-configs | 已读MCP工具选择说明；V1不依赖MCP实现全部循环 |
| S05 | https://github.com/mims-harvard/ToolUniverse | 仅列V1.1调研入口，本次未重核，不据此承诺兼容 |
| S06 | https://clinicaltrials.gov/data-api/api | API入口可达，JS文档正文未完整解析；字段需M0真实响应确认 |
| S06a | https://www.nlm.nih.gov/pubs/techbull/ma24/ma24_clinicaltrials_api.html | 已读NLM官方API v2说明：REST/JSON/OpenAPI |
| S07 | https://pubmed.ncbi.nlm.nih.gov/about/ | 已读PubMed范围；不是全文数据库 |
| S08 | https://eutilities.github.io/site/API_Key/usageandkey/ | 已读NCBI用量规则；无key3请求/秒、有key默认10；部署前复核 |
| S09 | https://open.fda.gov/apis/drug/label/ | 后续标签范围核验入口；非V1已实现来源 |
| S10 | https://open.fda.gov/apis/authentication/ | 后续配额核验入口；本次未重核 |
| S11 | https://open.fda.gov/apis/drug/event/ | 后续不良事件局限核验入口；V1不实现 |
| S12 | https://pmc.ncbi.nlm.nih.gov/tools/openftlist/ | 已读全文许可/自动获取限制；本包不附论文全文 |
| S13 | https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html | 安全核对入口，实施时复核；本包不是安全认证 |
| S14 | https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html | 提示注入防护核对入口，实施时复核 |
| S15 | https://nextjs.org/docs/app/guides/static-exports | 已读官方静态导出方案；动态路径/服务端能力需按锁定版本验收 |
| S16 | https://raw.githubusercontent.com/assafelovic/gpt-researcher/main/gpt_researcher/skills/researcher.py | 已读取采集模块；二开接口不是官方稳定承诺 |
| S17 | https://docs.gptr.dev/docs/gpt-researcher/search-engines | 已读检索源/自定义检索说明；PubMedCentral不能当作PubMed全集 |
| S18 | https://raw.githubusercontent.com/assafelovic/gpt-researcher/main/pyproject.toml | 已读依赖元数据；运行依赖需真实安装验证 |
| S19 | https://raw.githubusercontent.com/assafelovic/gpt-researcher/main/docker-compose.yml | 已读上游部署文件；本项目不照搬开发前端服务 |

## 重要限制
未执行GPT Researcher安装、真实模型/来源/SMTP请求与4核8GB压测，未锁定SHA；源API页面可达不等于真实接口验证通过。数据结构中的预期字段映射必须经过适配器contract test。
所有fixtures/原型药物、试验、计数和进度是原创虚构测试数据。不存在真实临床疗效结论。本包复用并调整用户此前PharmaScope规格中的领域/证据规则，运行架构以本Lite包为准。
