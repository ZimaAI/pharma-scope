# 13｜部署、配置与运维手册

## 1. 当前可运行与不可运行
可运行：`prototype/index.html`离线原型；`python scripts/verify_context.py`文档/合同校验。
待实现：真实FastAPI/Worker、GPTR Fork、数据库迁移、Docker镜像、SMTP。`deploy/compose.target.yaml`是待实现服务的部署模板，镜像使用必须填的变量，不是已经存在的可下载产品。

## 2. 环境拆分
`demo`使用fixture/replay，不要求模型密钥；`live`只允许官方适配器/真实模型。live缺凭据启动诊断失败，不回退demo。原型没有live模式。
账户由管理员CLI创建；生产随机强密码并强制修改，禁止固定演示账户。Cookie在HTTPS下Secure、HttpOnly、SameSite=Lax；部署同源Nginx，CSRF和Origin校验。

## 3. 配置来源
`config/lite.yaml`是项目非敏感配置；`.env.example`列环境变量。上游模型/Embedding配置映射只能由adapter实现，禁止逐请求修改全局os.environ造成串用户。API不持有模型Key，只有Worker持有。
密钥写部署环境/只读secret文件，不进Git/日志/报告。SMTP默认关闭，只有显式授权后启用外发；开发用测试邮箱或本地捕获器。source requests使用开发者tool/email身份，不传用户邮箱。

## 4. 部署顺序（服务实现后）
锁定依赖和GPTR提交→构建镜像→准备数据库/文件卷→执行迁移→创建管理员/工作区→写环境变量→启动PG/API/Worker/Nginx→health/readiness→fixture smoke→live来源小查询→live单任务→检查用量与内存→才开放访问。
迁移使用独立账号；运行账号不得更新不可变快照/版本。DB端口不映射公网。原型可以通过`python -m http.server 8000 --directory prototype`临时查看，不将该开发服务器当正式入口。

## 5. 健康与日志
`GET /health/live`只反映进程；`GET /health/ready`反映DB和关键配置，不在每次探测调用付费模型或真实来源。数据源健康显示最近请求时间与状态，不用一个绿色圆点承诺全天在线。
日志采用request_id/run_id/job_id，敏感字段脱敏。SSE使用持久run_event，Nginx关闭proxy_buffering/cache，15秒心跳；断开不取消任务。详细调用日志默认90天，审计180天，可配置。

## 6. 备份与恢复
数据库与私有文件卷一致备份，备份加密并保存在另一故障域；仅同盘复制不是灾备。建议每天备份，项目恢复目标RPO<=24h、RTO<=2h，尚未实测。恢复演练确认报告引用、session失效策略、job租约重置与投递unknown不误重发。

## 7. 运维故障流程
来源429/5xx：分清限流和空结果，减速重试；GPTR失败：保存已完成证据和错误，检查预算/模型能力；Worker重启：租约到期回收，完整checkpoint恢复或recovery_required；SMTP未知：冻结重发并人工核对；磁盘不足：暂停非关键摄入，不删除已发布证据。

## 8. 发布与回滚
记录app image、upstream SHA、配置hash、migration版本、前端构建hash；先备份再发布。数据迁移破坏性变更必须双写/兼容或备份恢复计划，不能简单切旧镜像假装数据库兼容。
更多限制见`21-resource-budget.md`和`delivery/TEST_RESULTS.md`。
