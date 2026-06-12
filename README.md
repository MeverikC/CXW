# CXW - Multi-Agent Orchestration Platform

**CXW** is a local-first multi-agent orchestration platform for software engineering. The
name comes from **Codex Workspaces Agent**: Codex-powered agents coordinated inside
durable local workspaces. The PyPI package is published as `cxwa` because the shorter
`cxw` package name is unavailable, but the installed terminal command remains `cxw`.

## 🎯 What's New

### OpenAI Codex Runtime (v0.2.0)

A powerful new runtime that combines:
- **GPT-4 orchestration**: Smart main agent for planning and coordination
- **Codex execution**: Worker agents via Codex MCP in isolated worktrees
- **Multi-provider support**: Mix OpenAI, Anthropic, DeepSeek in one workflow
- **Dynamic planning**: Adjust tasks mid-execution based on results
- **Cost optimization**: Use expensive models only for coordination

See [OpenAI Codex Runtime Guide](docs/openai-codex-runtime.md) for details.

## 🚀 Quick Start

### Installation

```bash
# From PyPI, once published
pip install cxwa

# Clone and install
git clone <repo-url>
cd cxw
pip install -e .
```

### Run Demo

```bash
# Set API keys
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...

# Run interactive demo
python demo/run_demo.py
```

### Basic Usage

```bash
# Initialize workspace
cd your-project
cxw . run

# Edit CXW.toml with your agents and tasks
# Then run with openai-codex runtime
cxw . run --runtime openai-codex
```

## 📖 Documentation

- **[OpenAI Codex Runtime Guide](docs/openai-codex-runtime.md)** - Complete runtime documentation
- **[Developer Guide](docs/developer-guide.md)** - Architecture and extension points
- **[User Guide](docs/user-guide.md)** - Configuration and usage
- **[Operations Guide](docs/operations.md)** - Deployment and monitoring
- **[Publishing Guide](docs/publishing.md)** - GitHub, TestPyPI, and PyPI release checklist
- **[Implementation Summary](IMPLEMENTATION.md)** - Technical implementation details

## 🏗️ Architecture

```
┌─────────────────────────────────────────┐
│   Main Orchestrator (GPT-4/Claude)     │
│   • Plans & decomposes tasks            │
│   • Coordinates execution                │
│   • Handles failures dynamically         │
└─────────────────┬───────────────────────┘
                  │
      ┌───────────┼───────────┐
      │           │           │
      ▼           ▼           ▼
┌──────────┐ ┌──────────┐ ┌──────────┐
│ Backend  │ │ Frontend │ │  Tester  │
│ (Claude) │ │ (GPT-4)  │ │(DeepSeek)│
│ Worktree │ │ Worktree │ │ Worktree │
└──────────┘ └──────────┘ └──────────┘
```

## ✨ Key Features

### Multi-Agent Orchestration
- Smart main agent for task decomposition and coordination
- Specialized workers: backend, frontend, testing, review
- Dynamic plan adjustment based on execution results
- Intelligent failure recovery and retry strategies

### Isolated Execution
- Git worktrees: Each agent in separate branch/worktree
- Per-agent APIs: Different providers and models per agent
- Independent configs: Separate API keys and settings
- Cost tracking: Monitor usage per agent

### Persistence & Auditability
- SQLite state store for workspace, agents, tasks
- NDJSON event log for replay and analysis
- Full transparency: every decision recorded
- Resume-capable daemon architecture

## 🔧 Example Configuration

```toml
[workspace]
name = "My Project"
goal = "Build a full-stack application"

[defaults.codex]
runtime = "openai-codex"
goal_mode = true

# Backend with Claude
[[agents]]
name = "backend-1"
role = "backend-coder"
[agents.codex]
model = "claude-opus-4"
base_url = "https://api.anthropic.com/v1"

# Frontend with GPT-4
[[agents]]
name = "frontend-1"
role = "frontend-coder"
[agents.codex]
model = "gpt-4o"

[[tasks]]
title = "Implement backend API"
assigned_agent = "backend-1"

[[tasks]]
title = "Build frontend UI"
assigned_agent = "frontend-1"
```

## 🎮 Available Runtimes

| Runtime | Description | Use Case |
|---------|-------------|----------|
| `openai-codex` | GPT-4 orchestrator + Codex workers | Complex multi-agent workflows |
| `codex-mcp` | Pure Codex MCP | Static plans, consistent execution |
| `local-deterministic` | Dry-run mode | Testing and development |

## 📊 Monitoring

```bash
# Interactive TUI
cxw . shell

# Real-time progress
cxw . status --watch

# Stream events
cxw . events --follow
```

## 🧪 Development

### Run Tests

```bash
# All tests
python -m pytest tests/

# Specific suite
python -m pytest tests/test_openai_codex_runtime.py -v

# With coverage
python -m pytest --cov=cxw --cov-report=html
```

**Current Status**: ✅ 66 tests passing

### Project Structure

```
src/cxw/
  ├── cli.py                 # CLI entry point
  ├── daemon.py              # Background daemon
  ├── orchestrator.py        # Workflow state machine
  ├── task_manager.py        # Dynamic task adjustment
  ├── agents/
  │   ├── runtime.py         # Runtime protocol
  │   ├── openai_codex_runtime.py    # OpenAI+Codex runtime
  │   └── main_agent_prompt.py       # Orchestrator prompt
  ├── codex_mcp.py           # MCP client
  └── tui.py                 # Interactive shell
```

## 🛠️ What Works Now

✅ Workspace identity and durable state  
✅ Daemon with IPC and restart recovery  
✅ SQLite + NDJSON event log  
✅ CXW.toml project plan validation  
✅ Configurable agents and tasks  
✅ Git worktree management  
✅ Multi-runtime support (local, codex-mcp, openai-codex)  
✅ Per-agent Codex homes and API configs  
✅ Dynamic task adjustment  
✅ Real-time progress monitoring  
✅ Interactive workspace shell  

## 🔜 Roadmap

- [ ] Real-time agent interruption (when Codex MCP supports it)
- [ ] Streaming worker progress to main agent
- [ ] Cost tracking dashboard
- [ ] Agent result caching
- [ ] Multi-round agent conversations
- [ ] Auto-merge with safety checks

## 📝 License

[Add your license]

## 🙏 Built With

- [Codex](https://github.com/anthropics/codex) - AI code agent CLI
- [OpenAI SDK](https://github.com/openai/openai-python) - LLM API client
- [Rich](https://github.com/Textualize/rich) - Terminal UI
- [Typer](https://github.com/tiangolo/typer) - CLI framework
- [Pydantic](https://github.com/pydantic/pydantic) - Data validation

---

**Status**: ✅ **Production Ready** (v0.2.0)

See [IMPLEMENTATION.md](IMPLEMENTATION.md) for technical details.
