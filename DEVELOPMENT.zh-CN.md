# Pharma Scope 二次开发指南

## 1. 仓库与分支

本项目基于 GPT Researcher，保留清理后的上游提交历史与许可证文件。
原始源码基线：`6f998577d547b1e54ec662dac63583aa11e3b84b`。

首次推送时，GitHub 检测到上游旧提交中的 LangSmith 密钥并阻止推送。
初始化使用 `git-filter-repo` 将该密钥从 `main` 的历史中替换掉；
已验证清理前后当前源码树完全一致，但受影响的历史提交哈希发生变化。
`upstream/main` 保留原始引用供比较，后续采用下文的挑选提交方式同步。

| 项目 | 配置 |
| --- | --- |
| 本地目录 | `D:\Develop\Projects\pharma-scope` |
| 唯一开发分支 | `main`，跟踪 `origin/main` |
| 自己的远程仓库 `origin` | `https://github.com/ZimaAI/pharma-scope.git` |
| 上游远程仓库 `upstream` | `https://github.com/assafelovic/gpt-researcher.git` |

直接在 `main` 开发、提交和推送即可，不需要 `develop` 或功能分支。
`origin/main`、`upstream/main` 是远程跟踪引用，不是额外的本地开发分支。
当前克隆已设置默认推送到 `origin`，普通拉取只接受快进更新。
这些 Git 本地配置不会随代码推送到 GitHub。

## 2. 本地启动（Windows PowerShell）

### 后端及内置简易页面

Python 版本要求为 3.11 或更高，项目 `.python-version` 使用 3.11。
本机已检测到 Python 3.12，可用下面的命令创建环境。
在项目根目录执行以下命令；虚拟环境只需首次创建：

```powershell
cd D:\Develop\Projects\pharma-scope
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

编辑根目录 `.env`，填写自己的密钥：

```dotenv
OPENAI_API_KEY=填写你的密钥
TAVILY_API_KEY=填写你的密钥
LANGUAGE=chinese
```

启动：

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

- 内置简易页面：<http://localhost:8000>
- API 文档：<http://localhost:8000/docs>

从仓库根目录运行时，Python 会直接使用这里的 `gpt_researcher/` 源码。
上述命令使用虚拟环境 Python 的完整路径，无需激活脚本或修改 PowerShell 执行策略。

默认模型见 `gpt_researcher/config/variables/default.py`。
如需切换，在 `.env` 配置 `FAST_LLM`、`SMART_LLM`、`STRATEGIC_LLM`，
格式为 `提供商:模型名`，并选择自己账号实际可用的模型。
使用兼容 OpenAI 的服务时，还可配置 `OPENAI_BASE_URL`；
`EMBEDDING` 是单独的嵌入模型配置，需要对应服务支持。
修改 `.env` 后重启后端。

### Next.js 前端

需要 Node.js 和 npm。可使用 Node.js 22；项目自带的旧 Docker 开发镜像使用 Node 18。
后端保持运行，在第二个 PowerShell 窗口执行：

```powershell
cd D:\Develop\Projects\pharma-scope\frontend\nextjs
npm install --legacy-peer-deps
$env:NEXT_PUBLIC_GPTR_API_URL = 'http://localhost:8000'
npm run dev
```

访问 <http://localhost:3000>。安装参数与上游 `Dockerfile.dev` 保持一致。
也可以将 `NEXT_PUBLIC_GPTR_API_URL=http://localhost:8000` 写入前端目录的
`.env.local`，这样不必在每次启动时设置环境变量。
API 密钥放在后端 `.env`；`NEXT_PUBLIC_` 变量会进入浏览器代码。

### Docker 方式

安装并启动 Docker Desktop、填写根目录 `.env` 后，可从项目根目录运行：

```powershell
$env:PWD = (Get-Location).Path
docker compose up --build gpt-researcher gptr-nextjs
```

`PWD` 对应现有 Compose 中的本地卷路径。页面端口仍为 3000，后端为 8000。
若 Windows 原生环境的 PDF 导出遇到 WeasyPrint 系统库问题，可使用 Docker 运行后端。

## 3. 从哪里开始修改

典型调用方向：前端提交研究任务 → FastAPI / WebSocket → 研究流程 → 检索、抓取 → 报告生成。

| 想修改的内容 | 主要入口 |
| --- | --- |
| 页面、品牌、交互 | `frontend/nextjs/app/`、`frontend/nextjs/components/`、`frontend/nextjs/src/GPTResearcher.tsx` |
| 进度消息和前后端通信 | `frontend/nextjs/hooks/useWebSocket.ts`、`backend/server/websocket_manager.py` |
| API、文件上传、报告接口 | `backend/server/app.py` |
| 研究任务总入口 | `gpt_researcher/agent.py` 中的 `GPTResearcher` |
| 搜索与研究编排 | `gpt_researcher/skills/researcher.py` |
| 深度研究 | `gpt_researcher/skills/deep_research.py`、`backend/report_type/` |
| 提示词和报告写作 | `gpt_researcher/prompts.py`、`gpt_researcher/skills/writer.py` |
| 数据源适配 | `gpt_researcher/retrievers/` |
| 注册新检索器 | `gpt_researcher/actions/retriever.py`、`gpt_researcher/retrievers/utils.py` |
| 模型、语言、研究深度等配置 | `.env`、`gpt_researcher/config/config.py`、`gpt_researcher/config/variables/default.py` |
| PDF / Word 导出 | `backend/utils.py` |
| 测试 | `tests/` |

如果 Pharma Scope 用于医药研究，可按下面顺序推进：

1. 先跑通一个完整研究任务，确认检索、引用和报告展示。
2. 调整研究角色、中文报告提示词和报告章节，再修改页面品牌与输入表单。
3. 复用现有 `pubmed_central`、`openalex` 等检索器，随后再接入自己的数据源。
4. 业务流程稳定后再调整底层研究编排。

例如可在 `.env` 中配置多检索器：

```dotenv
RETRIEVER=tavily,pubmed_central,openalex
LANGUAGE=chinese
```

`pubmed_central` 默认使用 PMC 全文库；相关参数见 `.env.example` 的
`NCBI_API_KEY`、`PUBMED_DB`、`OPENALEX_EMAIL`、`OPENALEX_API_KEY`。
这只是可选的开发方向，初始化没有修改项目的检索和研究行为。

## 4. 个人开发日常流程

在项目根目录操作：

```powershell
git switch main
git pull --ff-only origin main
# 修改代码并做相关验证
git status
git diff
git add <本次修改的文件路径>
git commit -m "feat: 描述本次功能"
git push origin main
```

将尖括号占位符替换为真实路径。按功能分批提交，便于回退和定位问题。
`.env`、前端 `.env.local`、`.venv/`、`node_modules/`、`outputs/`、`my-docs/`
已有忽略规则。提交前检查暂存内容；运行生成的其他文件不一定被忽略。

修改前端后可在前端目录运行 `npm run build`。
修改 Python 逻辑后，为改动选择相关测试；测试工具可安装为：

```powershell
.\.venv\Scripts\python.exe -m pip install pytest pytest-asyncio pytest-timeout pytest-forked
.\.venv\Scripts\python.exe -m pytest tests/test_相关模块.py
```

测试文件名是占位符。部分集成测试需要真实密钥及网络，调用研究任务也会使用配置的 API。
仓库保留上游 GitHub Actions：`tests.yml` 会在推送 `main` 时运行；
上游 AWS 部署工作流主要针对 `master`，尚未为本项目配置部署。

## 5. 挑选上游更新

由于上游原始历史中包含触发推送保护的密钥，直接合并 `upstream/main`
会再次引入这些旧提交。这里采用 `cherry-pick`，只引入需要的代码改动。
先提交当前修改，确保 `git status` 干净，再查看初始化基线之后的更新：

```powershell
git switch main
git pull --ff-only origin main
git fetch upstream
git log --oneline 6f998577d547b1e54ec662dac63583aa11e3b84b..upstream/main
# 查看并选择需要的非合并提交
git show <上游提交哈希>
git cherry-pick <上游提交哈希>
# 验证自己的功能
git push origin main
```

尖括号内容需替换为真实哈希；有依赖的提交应按先后顺序引入。
出现冲突时，编辑冲突文件，执行 `git add <已解决的文件>`、
`git cherry-pick --continue`；若要取消，执行 `git cherry-pick --abort`。
在提交说明中记录原始上游哈希，避免重复引入。
大版本整体同步需要先对新上游历史做相同清理，再评估合并。
日常开发仍然只使用 `main`，不需要额外分支或强制推送。

在另一台机器上首次克隆本项目后，补充本地配置：

```powershell
git clone --branch main --single-branch https://github.com/ZimaAI/pharma-scope.git
cd pharma-scope
git remote add -t main upstream https://github.com/assafelovic/gpt-researcher.git
git config --local remote.pushDefault origin
git config --local push.default simple
git config --local pull.ff only
```

## 6. 初始化范围

本次完成源码拉取、单 `main` 分支和远程配置、开发指南及推送。
没有安装应用依赖、配置真实 API 密钥或执行端到端研究任务。
上游 `README.md` 原文保留在项目介绍下方，许可证保留在 `LICENSE`。
