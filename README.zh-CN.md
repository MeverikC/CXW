# CXW - 本地优先的多 Agent 工程编排平台

[English](README.md)

**CXW** 是一个面向软件工程的本地优先多 Agent 编排平台。名字来自
**Codex Workspaces Agent**：在持久化的本地 workspace 中协调多个 Codex 驱动的工程
agent。由于 PyPI 上 `cxw` 包名不可用，发布包名使用 `cxwa`，但安装后的命令仍然是
`cxw`。

CXW 的目标不是做一个聊天应用，也不是简单包一层多终端。它把一个本地仓库视为一个
工程 workspace，由 daemon 统一管理计划、任务、agent、git worktree、事件流和审查
记录。用户从终端里操作，体验接近“在命令行里管理一个软件工程团队”。

## 当前能力

- workspace 按仓库路径识别，并把状态持久化到 `~/.cxw/workspaces/<workspace_id>`
- 后台 daemon 作为单一事实来源，多个终端可以连接同一个 workspace
- SQLite 状态库和 NDJSON 事件日志，支持审计、回放和恢复
- `CXW.toml` 项目计划文件，声明 main agent、worker agent、runtime 和任务
- 每个 worker agent 拥有独立 git worktree 和 `cxw/<agent-name>` 分支
- 支持 `local-deterministic`、`codex-mcp`、`openai-codex` 等 runtime 边界
- 支持实时日志、agent attach、Rich 状态视图和 prompt-toolkit 交互 shell
- 实现 review gate 和 merge plan，最终合并仍由人类审批
- 为 GitHub、TestPyPI、PyPI 发布准备了 CI 和手动发布 workflow

## 安装

从 PyPI 安装，发布后可使用：

```bash
pip install cxwa
```

从源码安装：

```bash
git clone https://github.com/MeverikC/CXW.git
cd CXW
python -m pip install -e .
```

开发安装：

```bash
python -m pip install -e ".[dev]"
```

发布工具安装：

```bash
python -m pip install -e ".[publish]"
```

## 快速开始

进入任意本地 Git 仓库：

```bash
cxw /path/to/repo
```

第一次启动时，CXW 会创建或检查：

```text
/path/to/repo/CXW.toml
~/.cxw/workspaces/<workspace_id>/
```

检查配置：

```bash
cxw /path/to/repo config-check
```

生成计划草案：

```bash
cxw /path/to/repo plan auto "实现一个 React + FastAPI 抽奖应用"
```

执行计划：

```bash
cxw /path/to/repo run
```

指定 runtime：

```bash
cxw /path/to/repo run --runtime local-deterministic
cxw /path/to/repo run --runtime codex-mcp
cxw /path/to/repo run --runtime openai-codex
```

## 常用命令

```bash
# 查看 workspace 状态
cxw /path/to/repo status

# 进入交互 shell
cxw /path/to/repo shell

# 回放 workspace 事件
cxw /path/to/repo logs

# 查看某个 agent 的事件
cxw /path/to/repo logs backend-1

# 实时 attach 到某个 agent
cxw /path/to/repo backend-1

# 停止某个 agent
cxw /path/to/repo stop backend-1

# daemon 恢复并重新评估持久化状态
cxw /path/to/repo resume

# 生成 review/test/risk/merge 汇总
cxw /path/to/repo summaries

# 查看 daemon 健康状态
cxw /path/to/repo daemon-health

# 停止 daemon
cxw /path/to/repo daemon-stop
```

## `CXW.toml` 示例

```toml
[workspace]
name = "My Project"
goal = "Build a full-stack application"

[main_agent]
name = "main-1"
instructions = "Plan, schedule, monitor, delegate approvals, and keep CXW moving."

[defaults.codex]
runtime = "codex-mcp"
goal_mode = true
approval_delegate = "main-1"
approval_policy = "on-request"
sandbox_mode = "workspace-write"

[[agents]]
name = "planner-1"
role = "planner"
instructions = "Plan the work and keep approval boundaries explicit."

[[agents]]
name = "backend-1"
role = "backend-coder"
instructions = "Implement backend/API work in an isolated worktree."

[[agents]]
name = "tester-1"
role = "tester"
instructions = "Run focused verification and report risks."

[[tasks]]
title = "Implement backend API"
description = "Create the backend API for the requested workflow."
assigned_agent = "backend-1"

[[tasks]]
title = "Verify backend API"
description = "Run focused tests and summarize remaining risk."
assigned_agent = "tester-1"
```

## 架构

```text
                CLI
                 |
                 v
             CXW Daemon
                 |
    ------------------------------
    |            |              |
Event Bus   State Store   Agent Runtime
    |            |              |
    ------------------------------
                 |
         Worktree Manager
                 |
           Git Worktrees
                 |
          Codex MCP Agents
```

核心模块：

- `cxw.cli`：Typer 命令入口和 Rich 终端渲染
- `cxw.daemon`：daemon 生命周期、IPC 请求处理、workspace snapshot
- `cxw.ipc`：基于 Unix socket 或本地 TCP fallback 的 JSON-lines 协议
- `cxw.store`：SQLite 持久化和 NDJSON 事件日志
- `cxw.events`：持久化事件总线和实时订阅
- `cxw.orchestrator`：显式 workflow state machine 和调度逻辑
- `cxw.worktrees`：一 agent 一 worktree 的 git worktree 管理
- `cxw.agents.runtime`：runtime adapter 协议和实现
- `cxw.review` / `cxw.summaries`：review gate、风险摘要和 merge plan

## Runtime

| Runtime | 说明 | 适用场景 |
| --- | --- | --- |
| `local-deterministic` | 不调用外部模型，只记录任务派发边界 | 本地开发、测试、dry run |
| `codex-mcp` | worker 通过 Codex MCP 执行任务 | 静态计划、单层 worker 执行 |
| `openai-codex` | main agent 使用 OpenAI SDK，worker 通过 Codex MCP 执行 | 更复杂的动态拆解和协调 |
| `openai-agents` | 可选 OpenAI Agents SDK runtime | 实验性 SDK 集成 |

Codex MCP 相关环境变量：

```bash
export CXW_CODEX_BIN=codex
export CXW_CODEX_MCP_COMMAND="codex mcp-server"
```

指定 CXW runtime：

```bash
export CXW_AGENT_RUNTIME=codex-mcp
```

## 本地状态和安全

CXW 会创建本地运行状态：

```text
~/.cxw/workspaces/<workspace_id>/state.sqlite3
~/.cxw/workspaces/<workspace_id>/events.ndjson
~/.cxw/workspaces/<workspace_id>/worktrees/
```

它也会在目标仓库下准备 agent 专用 Codex home：

```text
<repo>/.codex/cxw/main-1/
<repo>/.codex/cxw/agents/<agent-name>/
```

`.codex/`、`.cxw/`、构建产物、虚拟环境和日志都应保持未跟踪。仓库中的 `.gitignore`
已经覆盖这些运行态目录，避免把 `auth.json`、token、SQLite 状态或 worktree 输出提交到
GitHub。

## 开发

运行测试：

```bash
python -m pytest -p no:cacheprovider
```

构建发布包：

```bash
python -m pip install -e ".[publish]"
python -m build
python -m twine check dist/*
```

发布流程见：

- [Publishing Guide](docs/publishing.md)
- [Developer Guide](docs/developer-guide.md)
- [User Guide](docs/user-guide.md)
- [Operations Guide](docs/operations.md)

## 状态

CXW 目前处于早期 alpha 阶段。核心的 daemon、状态持久化、事件流、worktree 隔离、
runtime adapter、review gate 和恢复流程已经建立；真实 Codex MCP 执行、review 自动化、
成本统计和更强的中断控制仍需要继续打磨。

## License

暂未添加 License。
