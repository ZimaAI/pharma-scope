# 23｜原型说明、页面状态与正式前端验收

原型文件为 `prototype/index.html`。它是可操作的单文件演示，不是已经与后端联调的Next.js项目。本文把视觉与业务合同连接起来；不能以“原型按钮可点”替代正式API验收。

## 1. 页面到服务的映射
| 原型哈希 | 页面主要组件 | 正式服务职责 | 完成判据 |
|---|---|---|---|
| #dashboard | 指标卡、近期变化、待审核、来源状态 | workspace范围统计及数据新鲜度 | 区分基线与变化；旧缓存标明as_of |
| #drugs / #drugs/PX-101 | 档案搜索、新增、别名与关联 | entities/drugs/aliases | 未确认别名不能自动合并；跨工作区拒绝 |
| #trials / #trials/DEMO-CT-001 | 结构化列表、状态筛选、详情 | sources/projections/observations | 值、类型、来源日期精度与观察时间并存 |
| #changes / #changes/EV-01 | 差异双栏、来源更正、回退 | events/revisions/snapshots | 首次导入不算变化，A→B→C→A不能漏事件 |
| #literature | 文献元数据、摘要抽屉 | publications/evidence | 没有摘要明确展示，不补造全文 |
| #research / #research/RUN-001 | 任务表单、执行轨迹、预算、覆盖 | jobs/runs/tool_calls/SSE | 返回202后离开页面仍继续；重连不丢事件 |
| #reports / #reports/REP-001 | 正文、结论证据、版本、审核 | reports/versions/reviews/publish | 自审/旧批准/缺证据均拒绝；发布版本不可变 |
| #subscriptions | 频率、启停、手动触发、交付记录 | schedules/outbox/inbox | 不用研究完成水位替代交付水位；未知发送可见 |
| #settings | 来源、预算、模式、故障演示 | admin/source configuration | 密钥不回显；仅管理员变更；live不回退demo |

具体URL、字段与枚举以 `contracts/openapi.yaml` 为准。上述模块名不是HTTP路径承诺。正式前端同源使用 `/api/v1`；详情示例 `/trials/detail/?id=<uuid>`。SSR、server actions、运行时Node不属于本版部署方案。

## 2. 原型状态与合同状态不能直接照搬
原型的 `queued/running/completed/partial/cancelled` 是演示状态。正式实现遵守功能规格和OpenAPI的状态枚举与完整状态机，包括持久化失败、等待澄清、恢复所需信息和取消中的状态。显示文案不作为数据库枚举。
原型报告的`draft/in_review/approved/published/changes_requested`只演示可见阶段；正式端的版本、内容hash、review记录、published pointer和撤回行为均按合同实现。

## 3. 交互细则
研究表单默认药物、来源、截止时间可见；格式错误定位字段，重复提交携带同一Idempotency-Key。创建成功返回run_id再订阅SSE。预算不足、来源失败、人工等待分别呈现，不使用一个“失败”覆盖所有状态。
证据抽屉展示对象、快照、原值、定位、观察时间、来源权限说明；关闭后焦点回原触发器。找不到定位则展示证据失效，不显示伪造片段。
审核复选框必须随报告版本/角色切换清除。批准请求绑定version_id和content_hash；过期返回409并要求重新读取。作者/编辑者限制由服务端执行。界面角色下拉在正式产品中移除。
表格小屏局部横向滚动，不让整页溢出；状态不能仅用颜色表达。加载骨架不显示假计数，空列表不能声称官方数据库没有记录。

## 4. 测试层分离
`prototype/smoke_test.py`证明离线DOM行为与部分响应式布局。正式Playwright E2E必须连接已启动API/数据库，验证登录、角色、SSE断线、409版本冲突、取消、重启恢复和导出授权。真实数据与模型验证再独立执行，不能三者互相替代。
