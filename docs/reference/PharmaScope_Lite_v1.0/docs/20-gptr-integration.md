# 20｜GPT Researcher源码二开方案与适配探针

## 1. 已核对与未核对
2026-09-22读取了官方README、`gpt_researcher/agent.py`、`skills/researcher.py`、默认配置和pyproject。当前源码存在`ResearchConductor`、`ReportGenerator`以及`conduct_research()`/`write_report()`入口。[S01][S02][S03][S16]
未下载和运行完整仓库，未验证固定commit；`delivery/upstream.lock.json`保持未锁定。Python版本以锁定提交依赖为准，不能混用旧文档的版本要求与当前源码。

## 2. Fork而不是改名套壳
| 上游位置/能力 | 本项目策略 | 交付证明 |
|---|---|---|
| GPTResearcher Python入口/生命周期 | 保留；由builder注入领域conductor | 上游版本+适配测试 |
| ResearchConductor | 新增PharmaResearchConductor实现，替换开放抓取流程 | patch文件、Function Calling分支测试 |
| ReportGenerator/Prompt体系 | 复用写作与配置；增加结构化证据约束 | 同输入基线对照 |
| 来源/上下文记录 | 保留有用能力，补证据ID/版本元数据 | EvidencePacket合同测试 |
| BrowserManager/爬虫/图片/本地文档 | Lite路径惰性初始化或禁用；不自动安装启动浏览器 | 无浏览器任务验收、依赖清单 |
| Memory/Embedding初始化 | 可选远程Embedding，默认结构化证据不需要；必要时最小patch延迟创建 | 无Embedding密钥也能跑Lite探针 |
| GPTR Web/Next演示 | 仅参考，正式Pharma UI独立静态导出 | 页面验收 |
| checkpoint/RBAC/变化追踪/审核/队列 | 自己实现，不声称上游提供 | 模块与回归用例 |

## 3. 最小patch计划
PATCH-01：在Fork中引入构造/工厂注入点，允许选择PharmaResearchConductor；不能向原始SDK凭空传未支持的构造参数。
PATCH-02：Lite profile禁用递归deep research、通用scraper、图片生成、浏览器与未使用的Memory初始化；不可为了减依赖随意删除import后宣称可运行。
PATCH-03：接入模型调用计量/取消钩子，覆盖采集、写作、修复和核验；所有请求经过同一预算对象。
PATCH-04：映射工具和行动事件；记录批次完成的消息检查点；默认不输出隐含推理/凭据。
PATCH-05：上游输出桥接为EvidencePacket和结构化草稿；添加不联网回归测试。

每个patch需说明原始commit、修改文件、目的、上游升级冲突点和测试；用`patches/README.md`记录。无需改上游代码的扩展放在业务包，不把整个仓库复制一份再无法升级。

## 4. 接入伪代码（不是可直接调用的上游示例）
```python
# build_pharma_researcher是项目新增工厂；conductor注入点需要上述patch。
researcher = build_pharma_researcher(
    pinned_config=runtime_config,
    conductor=PharmaResearchConductor(context, tool_gateway, checkpoints, budget),
    events=domain_event_sink,
)
evidence_packet = await researcher.conduct_research()
# 已持久化ID与片段是事实输入；不把可变网页当最终证据。
report_candidate = await structured_writer.from_packet(evidence_packet)
validated = await report_service.validate_candidate(report_candidate, context)
```
不得将本伪代码复制后改名成“SDK官方用法”。M0后在adapter内实现具体映射并补可运行最小示例。

## 5. M0阻断性验证清单
GP-01 固定SHA、许可证、依赖锁可安装；生成SBOM或依赖清单。
GP-02 无Tavily、浏览器、Embedding凭据时能通过本地fixture工具完成Lite探针，不偷偷走默认互联网检索。
GP-03 主模型支持Function Calling；多段tool参数正确拼接，拒绝不完整JSON。
GP-04 工具结果进入下一轮，至少两种问题产生不同序列；仅顺序跑固定工具不合格。
GP-05 workspace、user、run由可信上下文传递；模型不能越权覆盖。
GP-06 取消/超时可回收执行；外部调用不可取消时如实标记，并测试子进程回收。
GP-07 所有模型调用被计量，无usage时为unknown；不把get_costs误当tokens。
GP-08 相同完整checkpoint能恢复；半轮中断返回recovery_required或重跑受控读操作，不宣称无损续写。
GP-09 最小研究进程内存测量并记录峰值，明确是否需要提高3GB worker预算。

任何探针失败先修适配层，不通过偷偷增加DeerFlow/另一套Agent框架解决。确需改变架构时写ADR与受影响合同，保留当前硬约束。

## 6. 配置漂移与升级
本次当前默认配置含较高爬取并发和不同模型设置；本项目显式配置模型角色，不依赖上游默认模型名称。[S03] `main`只用于调研，不用于部署。每次升级先锁候选SHA，重跑GP-01至09和黄金用例，再替换生产锁。
许可证与原始版权声明保留；简历注明“基于GPT Researcher二开”，新增模块用提交/测试证据说明，不伪称从零自研整个Agent平台。
