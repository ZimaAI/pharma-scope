# PharmaScope Lite｜医药研发情报与临床试验变化追踪平台

**文档版本：Lite 1.0.0 · 2026-09-22 · 交付类型：产品/工程规格 + 可交互原型 + 机器合同**

> 这是供编码 Agent 实现的完整设计包，不是已完成的后端产品。`prototype/index.html` 是可以离线操作的前端原型；研究进度是明确标识的模拟回放。真实模型、真实来源、数据库迁移和4核8GB部署尚未运行。

## 1. 产品与服务器基线
面向研发信息研究，将公开药物、临床试验登记及文献整理为**可追踪变化、可核对证据、可人工审核、可订阅交付**的研究报告。不是诊疗系统，不提供患者匹配、处方、剂量或疗效认证。

本版完全替代前案的运行架构：**只使用 GPT Researcher，不使用 DeerFlow**。部署按4核CPU、8GB内存设计；大模型通过外部API调用；首版1个研究执行槽、2个外部HTTP请求并发；无本地模型、浏览器集群、OCR、向量数据库、Redis或独立消息中间件。资源上限是初始设计预算，不是压测结果。

## 2. 固定技术路线
| 层 | Lite V1选择 |
|---|---|
| 前端 | Next.js / React / TypeScript；Tailwind CSS / shadcn/ui；静态导出，生产不运行Node服务 |
| 后端 | Python 3.11或以上，实际版本依上游锁定；FastAPI / Pydantic / SQLAlchemy / Alembic |
| Agent | Fork GPT Researcher，新增受预算约束的 PharmaResearchConductor；通过单一适配器使用，具体改造见docs/20 |
| 数据 | PostgreSQL；私有本地文件卷；source snapshot与报告事实不放临时内存 |
| 来源 | ClinicalTrials.gov API v2 + PubMed E-utilities；首版只需结构化资料与摘要 |
| 部署 | Nginx静态资源/反代、API、Worker、PostgreSQL，共4个常驻容器 |
| 环境 | demo=replay+虚构fixture；live=真实来源+真实模型；不允许live失败后偷偷回退demo |

## 3. 先看哪里
- [需求文档](docs/01-prd.md)、[功能规格](docs/03-functional-spec.md)、[架构](docs/04-architecture.md)。
- [GPT Researcher二开边界](docs/20-gptr-integration.md)、[4核8GB专项](docs/21-resource-budget.md)。
- [交互原型](prototype/index.html)、[原型使用指南](prototype/README.md)、[完整文档索引](docs/INDEX.md)。
- [设计规范](design.md)、[开发实施指令](CODEX_START.md)、[交接状态](delivery/STATE.md)。

## 4. 项目目录
```text
docs/             # PRD、规格、领域、架构、数据、Agent、运维、测试等
contracts/        # OpenAPI 3.1、JSON Schema、工具合同
prototype/        # 单HTML交互原型、浏览器测试、原型说明
fixtures/         # 全虚构药物/试验/证据/事件样例
acceptance/       # Gherkin验收场景；不冒充已执行集成测试
database/         # PostgreSQL初始DDL参考
config/ deploy/   # 应用配置、部署目标模板（后端待实现）
prompts/          # 研究/核查/变化解释Prompt
scripts/          # 文档、合同及样例验证
implementation/   # 待开发目录/模块清单
 delivery/        # 基线、测试证据、版本锁定状态
```

## 5. 使用与边界
解压后直接打开 `prototype/index.html`。原型无CDN、无外部字体、无联网要求。正式前端必须按Next.js技术栈重建组件和API层；不要把单HTML原型误称为正式前端源码。

开发按M0上游探针→M1基础业务→M2摄入/快照→M3真实Agent→M4审核/订阅→M5前端→M6验收推进。本包定义整个V1范围；可阶段验收，也可在已授权范围内连续实现。**生产部署、收费API调用、实际对外发信默认不授权。**

本包继承前案的领域与证据规则，但对Agent、资源预算、静态前端、检查点和部署方案进行了重写。`docs/00-baseline.md` 是当前架构权威源。不得重新引入已排除的运行底座。
