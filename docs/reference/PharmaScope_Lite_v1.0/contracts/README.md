# 机器可读合同

`openapi.yaml` 定义已实现 API 的请求及响应，`*.schema.json` 定义事件、研究输出、来源快照和工具结果；`tool-catalog.json` 列出真实 Lite conductor 允许调用的两个只读证据工具。来源发现和同步由持久化 worker 执行，模型只能检索及读取已通过 workspace、药物关联、来源和观察时间范围授权的证据。

运行模式明确为 `replay` 或 `live`。`gptr` 旧环境配置只作为 `live` 的输入别名，业务响应统一使用 `live`；这不代表真实模型调用已通过。模型缺凭据、来源故障、部分完成及未知用量有独立状态。`Usage.reserved_tokens` 是用于预算恢复的保守预留值，只有 `usage_quality=reported` 时才可把 `total_tokens` 当成供应商报告的 token 用量。

供应商原始 payload 保存在不可变快照，业务 projection 有独立版本。Workspace 与用户身份来自服务端可信上下文，不能由模型参数赋权。发布后的版本不允许更改；审核内容 hash 和引用证据由服务端校验。新增的来源检查及投递重试端点仍要求 RBAC 与 CSRF。

执行 `pytest backend/tests/test_api_contracts.py` 验证实际端点响应，包括非空同步产物、审核发布、投递、真实 GPTR 生命周期的离线 HTTP 合同测试、用量及 SSE 事件。离线 HTTP 测试明确使用 synthetic transport，不能作为真实来源或模型可用性的验收证据。运行 `python -m backend.live_probe --sources --model` 才会尝试真实外部服务，并保留缺配置/来源失败结果。

`make verify-docs` 校验合同引用、样例、hash、证据定位和文档链接；它不代替数据库、API、浏览器和实际外部服务验证。OpenAPI 和独立 Schema 必须同步维护，不能通过宽泛 `additionalProperties: true` 隐藏业务字段漂移。
