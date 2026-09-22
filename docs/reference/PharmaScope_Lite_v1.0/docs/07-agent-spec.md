# 07｜Agent规格、工具循环与研究合同

## 1. 真正的二开边界
保留GPT Researcher的Python应用入口、模型配置、研究上下文/来源聚合和报告能力，在Fork内部新增`PharmaResearchConductor`，用受控领域工具替换默认开放网页采集逻辑。不是在外层再跑一套Agent然后把字符串交给GPTR，也不是只换“医学专家”Prompt。[S01][S02]

首版一个主研究Agent，不生成/调度并行子Agent；采集并发最多2。MCP为V1.1可选接入方式，不是首版必需。上游有MCP能力并不等于本项目的自主工具循环、安全、持久化和领域规则已完成。[S04]

## 2. 冻结输入
`workspace_id/user_id/run_id`由服务端上下文注入。输入冻结question、approved drug/alias IDs、source_allowlist、time_range、knowledge_cutoff、配置/模型/Prompt/上游SHA、预算和重试策略。
内部状态含subquestions、performed_queries、known evidence IDs、unresolved、coverage、call ledger、messages/checkpoint。大正文在snapshot，模型消息只拿限定片段和引用。

## 3. 工具目录
机器合同在`contracts/tool-catalog.json`；所有工具是本项目新增，不是上游同名现成功能。
| 工具 | 输入摘要 | 返回 | 边界 |
|---|---|---|---|
| resolve_drug | text/limit | 已确认候选、歧义 | 不自动批准映射 |
| search_trials | drug_id/filters/limit | trial refs、snapshot refs、coverage | 已批准别名、有限页数 |
| search_publications | drug_id/terms/date_range/limit | 文献refs、摘要可用性 | 无全文抓取 |
| read_source_snapshot | snapshot_id/sections | 定位片段、evidence refs | 校验workspace和截止时间 |
| compare_trial_observations | trial/before/after | 类型化变化和前后证据 | 两次观察必须同record且顺序有效 |
| search_workspace_evidence | query/drug_ids/cutoff/limit | 现有证据匹配 | 不读其他workspace |
| inspect_evidence | evidence_ids | 原文、版本、hash | 每次最多10条 |
| request_clarification | question/options | 等待输入或后台缺口 | 不询问患者诊疗信息 |
| submit_research_draft | structured_report | 草稿候选和校验结果 | 不是发布工具 |

统一`ToolResult`在`contracts/tool-result.schema.json`：ok/data/error/coverage/provenance。ok=true且items=[]表示无结果；HTTP超时必须ok=false，不能返回空列表伪装成功。schema使用additionalProperties=false拒绝模型多传workspace/URL/秘密字段。

## 4. Function Calling循环
```text
while 尚有模型/工具预算 且 未取消:
  读取最后一个完整checkpoint
  将system + 用户范围 + 已持久messages + 允许的tools发给模型
  收集流：文本可以展示为临时草稿；tool参数必须完整后执行
  校验finish reason、参数JSON与工具名
  保存完整assistant message（含所有tool_calls）
  有tool_calls:
    每个call鉴权/预留预算/执行/记账；最多2个独立只读请求并发
    按call_id生成全部tool messages，包括结构化错误结果
    原子保存本轮工具结果与checkpoint，再进入下一轮
  无tool_calls:
    仅有普通文本不等于合格完成；要求合法结构化草稿或一次受预算约束修复
```
工具调用顺序、重复检索与补查由模型根据结果选择。`submit_research_draft`成功且所有本轮调用完成后终止采集；失败的引用检查返回可读错误让模型修正。服务端超预算则partial/failed，模型不能取消硬上限。

## 5. 报告形成
Conductor交付EvidencePacket和结构化候选。GPTR写作模块可整理带claim_key的叙述候选，但不得新增无证据事实。**最终ResearchOutput JSON为唯一权威**：写作若改变事实或范围，需重新进行引用/数值验证，再形成新版本；UI与Markdown导出从已审核JSON确定性渲染。不把GPTR输出的任意Markdown直接作为批准内容。
模型生成不符合JSON Schema时最多修复1次，预算照计。关键引用/数值校验未通过则verifying失败或partial，不自动转“已核验”。

## 6. Lite预算（项目默认，可在更低范围收紧）
一run工具调用最多20次、模型调用最多12次（包括选角色、写作、修复、语义检查）、候选记录最多100条、正文证据最多60片段、上下文拼装上限按模型能力配置且目标不超过24k token、全流程壁钟600秒；队列等待时间单独统计。
模型输入/输出总Token默认预算50,000（本项目总和口径，不是上下文窗口大小）。服务端调用前预留输入估计+输出上限，未知usage标estimated/unknown，不填0。单价未配置则cost=null；费用单位不混用。
`get_costs()`当前源码表示USD估计，不能当Token计数或提供商账单。[S02] Token以provider usage逐调用入账；自定义模型价格必须由配置明确提供。

## 7. 停止条件与三种必测路线
正常answered；无已证实变化no_verified_change；缺证据insufficient_evidence；来源故障source_unavailable；budget_exhausted；user_cancelled；runtime_error。连续3次无新增证据时允许提前结束但仍解释覆盖。
A：已有前后快照充分→少量读取→提交。
B：别名歧义→request_clarification→用户选对象→继续；订阅不能无限等待，返回partial。
C：PubMed失败→有限重试/使用标记为stale的旧证据→返回有缺口的partial，不说“无文献”。
用真实工具轨迹证明分支不同；replay不证明真实Agent能力。

## 8. 可信度与安全
硬核验：Schema、ID权限、snapshot hash、定位存在、quote一致、范围日期、可确定的数值及单位。
软核验：支持程度、歧义、相关性/因果混淆、摘要外推；由模型给建议并人工复核。不能把模型自审等同医学认证。
来源文本作为untrusted data；不能修改工具权限、发邮件、执行代码、改变对象范围。模型不能提供任意URL/SQL/bash；发布和投递不在工具表。

## 9. 检查点约束
消息检查点包含schema_version、run/attempt、完整消息序列、工具返回引用、已用预算和停止条件。不要记录隐藏推理作为用户界面；若提供商协议要求回传特定推理字段，仅在受保护服务端保存且按保留策略处理。
保存前校验每个assistant.tool_call均有一个关联tool结果；半截JSON流不进入checkpoint。重复执行工具以operation_key重放已持久结果；来源刷新必须显式成为新操作。

## 10. 应用自定义与上游配置严格分开
`PH_MAX_TOOL_CALLS/PH_MAX_MODEL_CALLS/PH_CONTEXT_TOKEN_LIMIT`等是本项目配置，必须自己实现。`MAX_SCRAPER_WORKERS/DEEP_RESEARCH_*`属于上游；设低值不能证明所有LLM与工具调用已受控。[S03] 完整配置见config/lite.yaml。
