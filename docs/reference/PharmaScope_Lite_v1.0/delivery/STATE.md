# 实施状态

- 项目：PharmaScope Lite v1.0；日期：2026-09-22。
- 当前状态：DESIGN_AND_PROTOTYPE_READY；不是DEMO_READY，也不是V1_RELEASE_READY。
- 已交付：完整产品/工程文档、机器合同、SQL参考、虚构fixtures、目标部署模板、离线交互原型、静态检查和27组原型DOM检查。
- 未完成：后端/Next正式前端、上游Fork依赖锁与实际探针、真实来源与模型、数据库执行、真实4核8GB压测。
- 下一步：实施者读取CODEX_START，执行M0并更新upstream.lock.json；不直接把compose.target.yaml当成已构建镜像运行。
- 模式：当前原型只有DEMO/REPLAY；正式live必须显式配置并独立验收。
- 浏览器检查限定：set_content离线DOM；未验证file URL策略与持久化；正式E2E仍未运行。
