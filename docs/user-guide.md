# CXW User Guide

This guide explains how to install CXW, start a workspace, write `CXW.toml`,
understand each command, and use the current runtimes.

## Requirements

- Python 3.11 or newer.
- Git installed and available as `git`.
- A local Git repository.
- For Codex MCP runtime: the `codex` CLI must be installed and logged in.

## Install

From the CXW source directory:

```bash
python -m pip install -e ".[dev]"
python -m pytest -p no:cacheprovider
```

For normal runtime use:

```bash
python -m pip install -e .
```

Verify the CLI:

```bash
cxw --help
```

## Start A Workspace

Run:

```bash
cxw /path/to/repo
```

If stdin/stdout are real TTYs, CXW starts the prompt-toolkit workspace shell. If
the command is run from a non-interactive process, CXW prints a status view and
exits.

Force the interactive shell:

```bash
cxw /path/to/repo --interactive
cxw /path/to/repo shell
```

Disable the interactive shell and print status:

```bash
cxw /path/to/repo --no-interactive
```

Inside the shell:

| Input | Effect |
| --- | --- |
| `/plan` | Show plan command help. |
| `/plan status` | Show `CXW.toml` validity, agent count, and task count. |
| `/plan init <goal>` | Generate an initial plan from a goal when the current file is missing or still a template. |
| `/plan auto <goal>` | Generate a plan draft from a goal; use `--force` to replace a non-template plan. |
| `/plan add agent <name> <role> <instructions...>` | Append one agent to `CXW.toml`. |
| `/plan add task <agent> <title> -- <description>` | Append one task to `CXW.toml`. |
| `/plan edit name <name>` or `/plan edit goal <goal>` | Edit workspace metadata. |
| `/run` | Create or reuse worker worktrees and dispatch pending tasks. |
| `/run --runtime <name>` | Dispatch once with an explicit runtime such as `local-deterministic` or `codex-mcp`. |
| `/status` or `/dashboard` | Render the full workspace dashboard tables. |
| `/final` | Record final human approval. |
| `/resume` | Publish a recovery/resume event. |
| `/clear` | Clear the screen and redraw the compact workspace header. |
| `/quit` or `/exit` | Leave the shell. |
| Any other text | Send a conversational message to the main agent and show its reply. |

The shell defaults to a compact conversation view. It does not redraw the full
status tables after every message. Use `/status` when you want the full dashboard.

Ask the main agent to draft a plan with a command:

```text
/plan auto 做一个前后端集成的抽奖项目，前端 React TailwindCSS，后端 FastAPI
```

If `CXW.toml` is still a generated template, `/plan auto` writes a valid draft
plan and replies with the next step. CXW will not overwrite a non-template file
unless you explicitly pass `--force`.

Normal conversation no longer triggers plan generation by keyword matching. Plan
changes go through `/plan ...` so they are auditable and scriptable.

## Local State

Workspace identity:

```text
workspace_id = sha256(abs_repo_path)
```

Workspace data:

```text
~/.cxw/workspaces/<workspace_id>
```

Durable files:

```text
state.sqlite3
events.ndjson
logs/
worktrees/
```

Repository files created by CXW:

```text
CXW.toml
.codex/cxw/main-1/
.codex/cxw/agents/<agent-name>/
```

`.codex/` is added to the repository `.gitignore`.

## Project Plan

CXW requires a repository-level project plan:

```text
<repo>/CXW.toml
```

If the file is missing, `cxw /path/to/repo` or `cxw /path/to/repo config-check`
creates a template and keeps the workspace in `COLLECT_REQUIREMENTS`.

Current preferred shape:

```toml
[workspace]
name = "Tiny Library"
goal = "Coordinate a focused Python library improvement."

[main_agent]
name = "main-1"
instructions = "Plan, schedule, monitor, delegate approvals, and keep CXW moving."

[defaults.codex]
runtime = "codex-mcp"
model = "gpt-5.5"
base_url = "http://127.0.0.1:15721/v1"
goal_mode = true
approval_delegate = "main-1"
approval_policy = "on-request"
sandbox_mode = "workspace-write"
max_iterations = 20
max_runtime_minutes = 60

[[agents]]
name = "planner-1"
role = "planner"
instructions = "Plan the work and keep approval boundaries explicit."

[[agents]]
name = "engineer-1"
role = "backend-coder"
instructions = "Implement the scoped repository change."

[agents.codex]
model = "gpt-5.5"
base_url = "http://127.0.0.1:15721/v1"

[[agents]]
name = "tester-1"
role = "tester"
instructions = "Run focused verification and report risks."

[[tasks]]
title = "Implement feature"
description = "Make the scoped code change."
assigned_agent = "engineer-1"

[[tasks]]
title = "Verify feature"
description = "Run focused tests and report remaining risk."
assigned_agent = "tester-1"
```

Compatibility note: older `[[roles]]` entries still work. New projects should
prefer `[[agents]]`.

Rules:

- `[workspace].name` and `[workspace].goal` are required.
- The main agent always exists; default name is `main-1`.
- At least one planner worker is required.
- At least one task is required.
- Every task must reference an existing non-planner worker.
- CXW does not assume frontend/backend agents unless `CXW.toml` defines them.

## Codex Homes

On workspace initialization CXW prepares:

```text
<repo>/.codex/cxw/main-1
```

When `CXW.toml` is valid, CXW also prepares each configured worker:

```text
<repo>/.codex/cxw/agents/<agent-name>
```

Each home contains:

```text
auth.json        copied from current CODEX_HOME or ~/.codex when available
config.toml      source Codex config plus CXW model/base_url overrides
cxw-agent.json   non-secret CXW metadata
```

If no source `auth.json` exists, CXW still creates the home and config, but
`auth_copied` is false. Real Codex MCP execution will fail later until Codex is
logged in.

## Command Reference

| Command | Purpose |
| --- | --- |
| `cxw /path/to/repo` | Start or attach to the workspace. In a TTY, opens the interactive shell. Outside a TTY, prints status. |
| `cxw /path/to/repo --interactive` | Force the prompt-toolkit shell. |
| `cxw /path/to/repo --no-interactive` | Start or attach, then print status and exit. |
| `cxw /path/to/repo shell` | Explicit shell command alias. |
| `cxw /path/to/repo plan <subcommand>` | Run the same plan command surface as interactive `/plan`. |
| `cxw /path/to/repo run [--runtime <name>]` | Run a valid plan: create worktrees, then dispatch pending tasks through the selected runtime. |
| `cxw /path/to/repo status` | Render workspace, plan, agents, recent events, and decisions. |
| `cxw /path/to/repo config-check` | Validate `CXW.toml`; create a template if missing. |
| `cxw /path/to/repo approve-plan` | Legacy alias for the old execution entrypoint. Prefer `run`. |
| `cxw /path/to/repo final-approve` | Record human final approval when workflow reaches final approval state. |
| `cxw /path/to/repo logs` | Replay persisted workspace events. |
| `cxw /path/to/repo logs <agent>` | Replay persisted events for one agent. |
| `cxw /path/to/repo <agent>` | Attach to a live event stream for one agent, tail-style. |
| `cxw /path/to/repo stop <agent>` | Mark an agent stopped. |
| `cxw /path/to/repo resume` | Reconnect/recover persisted state and publish a resume event. |
| `cxw /path/to/repo summaries` | Generate review, test, risk, and merge summaries. |
| `cxw /path/to/repo merge-plan` | Alias for `summaries`; renders merge-oriented output. |
| `cxw /path/to/repo workspace-info` | Show daemon health plus full workspace snapshot. |
| `cxw /path/to/repo daemon-health` | Check daemon health without starting a stopped daemon. |
| `cxw /path/to/repo daemon-stop` | Request daemon shutdown without deleting state. |
| `cxw /path/to/repo backup [archive]` | Create a portable workspace backup archive. |
| `cxw restore <archive> <repo>` | Restore a workspace backup for a repository path. |
| `cxw workspaces` | List known local CXW workspaces. |

Pass `--json` anywhere to request machine-readable output:

```bash
cxw --json /path/to/repo status
cxw /path/to/repo plan status --json
cxw /path/to/repo logs engineer-1 --json
```

For logs, JSON mode emits one event per line.

## Runtime Selection

Default runtime for older configs without an explicit `[defaults.codex].runtime`:

```bash
unset CXW_AGENT_RUNTIME
cxw /path/to/repo run --runtime local-deterministic
```

The `local-deterministic` runtime persists assignments and events without calling
external agents. It is useful for tests and dry runs.

Codex MCP runtime:

```bash
cxw /path/to/repo run
```

When `CXW.toml` declares `[defaults.codex] runtime = "codex-mcp"`, CXW starts
`codex mcp-server`, initializes it over JSONL stdio, lists tools, and calls the
real `codex` tool with task prompt, cwd, sandbox, approval policy, model, and
provider config.

Environment variable override:

```bash
export CXW_AGENT_RUNTIME=codex-mcp
cxw /path/to/repo run
```

Override the Codex command if needed:

```bash
export CXW_CODEX_BIN=/path/to/codex
export CXW_CODEX_MCP_COMMAND="codex mcp-server"
```

Optional OpenAI Agents SDK runtime:

```bash
python -m pip install -e ".[agents]"
export CXW_AGENT_RUNTIME=openai-agents
export CXW_OPENAI_AGENT_MODEL=gpt-5.1
cxw /path/to/repo run
```

## Verification Checklist

A new repository launch passes if:

- `CXW.toml` exists after launch.
- `<repo>/.codex/cxw/main-1/config.toml` exists after launch.
- `cxw /path/to/repo status` shows `main-1`.
- `cxw /path/to/repo config-check` reports invalid until all TODOs are replaced.

A configured project passes if:

- `cxw /path/to/repo config-check` reports valid.
- `cxw /path/to/repo run` creates worker worktrees for assigned agents.
- `cxw /path/to/repo logs <agent>` shows persisted assignment/worktree/runtime events.
