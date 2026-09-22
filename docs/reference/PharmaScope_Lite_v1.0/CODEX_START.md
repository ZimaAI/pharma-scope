# 提供给编码 Agent 的实施指令

把整个解压目录放到项目根目录，再将下面内容发送给编码工具。

```text
请基于本仓库的PharmaScope Lite文档包实现医药研发情报与临床试验变化追踪平台。
先实际读取README.md、AGENTS.md、docs/00-baseline.md、docs/20-gptr-integration.md、docs/21-resource-budget.md、design.md、contracts/和delivery/STATE.md。
本项目固定GPT Researcher二开、4核8GB、外部模型、一个研究槽。不得换成DeerFlow，不增加另一个独立Agent框架，不运行本地大模型、浏览器集群或Next开发服务器。
M0先检查并锁定真实上游SHA，验证PharmaResearchConductor插入点、默认依赖裁剪、工具循环、计量/取消/检查点。当前锁文件null代表未完成，不能凭空补SHA或假称探针通过。
按照M0→M1→M2→M3→M4→M5→M6推进，先后端合同/迁移/测试，再实现Next静态前端。原型是交互参考，不是已接后端代码。
不能将demo/replay代替live。缺凭据时完成离线测试并列明真实集成阻塞，不编造临床资料、患者信息、性能和成功率。
所有新增或修改页面前实际读取design.md。遵循OpenAPI、JSON Schema、领域不变量和验收场景；发现冲突先定位并更新受影响合同，不静默删范围。
本次默认连续完成可执行的本地工作，记录每阶段结果到delivery/STATE.md和TEST_RESULTS.md；若用户要求逐阶段验收，则在阶段出口暂停。生产部署、付费调用、对外发信未获授权，不自动执行。
最后交付可运行源码、依赖锁、迁移、启动说明、Mock/live分离配置、自动化测试、资源实测记录和未通过事项。不要把“设计完成”写成“软件实现完成”。
```
