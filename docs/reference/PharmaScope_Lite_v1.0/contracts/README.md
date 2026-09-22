# 机器可读合同

`openapi.yaml`定义API及其实体，`*.schema.json`定义独立事件/研究输出/来源快照/工具结果，`tool-catalog.json`定义服务端允许暴露的领域工具。它们是需要实现的合同，不代表API已存在。

使用规则：先生成类型并执行类型/样例检查，再编写路由；HTTP服务端不得直接透传供应商响应。公开来源payload保存在不可变快照，业务projection有独立版本。workspace与用户身份来自可信服务端上下文，不能由模型覆盖。

`tool-result.schema.json`为本项目新增的统一结果包装；业务工具成功、空结果、截断、请求失败分开。总候选数与Token预算等来自服务端profile，用户请求不得提高全局上限。对未返回usage的模型记unknown，不当成0。

OpenAPI与独立Schema出现冲突时，按AGENTS优先级记录并同步修复，不能静默挑选更宽松的一份。`scripts/verify_context.py`只验证部分结构、引用和样例；实施阶段还需完整OpenAPI校验器和实际端点contract tests。
