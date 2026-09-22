# PharmaScope Lite 前端设计规范

PharmaScope 是面向医药研发团队的情报工作台。页面以浅色背景、深色侧栏和蓝色主操作构成，优先呈现资料范围、版本、证据和审核状态。实现以 `docs/reference/PharmaScope_Lite_v1.0/design.md` 为规范来源，本文件记录项目中的落地方式。

## 视觉变量

```css
--ps-background: #F6F8FC;
--ps-surface: #FFFFFF;
--ps-surface-muted: #F0F3F9;
--ps-primary: #315EFB;
--ps-primary-hover: #254BDC;
--ps-primary-soft: #EEF2FF;
--ps-accent: #6D5AE6;
--ps-text-primary: #17243B;
--ps-text-secondary: #52617A;
--ps-text-muted: #6B7890;
--ps-border: #DDE4EF;
--ps-success: #157347;
--ps-warning: #9A5700;
--ps-danger: #BC2D3E;
--ps-sidebar: #142138;
```

使用系统字体栈 `Inter, -apple-system, BlinkMacSystemFont, Segoe UI, PingFang SC, Microsoft YaHei, sans-serif`，4px 间距栅格，侧栏 232px、顶栏 64px、主区 24px 边距。卡片圆角 12px，按钮和输入框 8px，弹窗和证据抽屉 16px。

## 交互原则

- 任何状态同时显示文字与图标；DEMO/LIVE、资料截止、来源覆盖和审核状态固定可见。
- 空列表区分“尚未同步”和“筛选无结果”，错误提示包含 `request_id` 和重试动作。
- 列表使用 cursor 分页，长名称允许换行；详情页通过证据抽屉查看快照、版本和字段路径。
- 主按钮在提交期间保留原文并显示加载状态；危险操作写明动作。支持键盘焦点环、Escape 关闭抽屉以及移动端导航抽屉。
- 前端优先调用 `/api/v1/workspaces/{workspace_id}` 合同接口，开发环境接口不可用时只显示明确标记为 DEMO 的虚构数据。

## 页面验收

在 1440×900、1024×768、390×844 视口检查侧栏折叠、表格横向滚动、抽屉、焦点和长英文标识。业务页面不复制原型脚本，不将虚构数据当作临床事实。
