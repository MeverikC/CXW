# CXW Developer Guide

This guide describes the current codebase and the extension points used to grow
CXW into a production-grade local-first orchestration platform.

## Project Layout

```text
src/cxw/
  cli.py              Typer command entry point.
  daemon.py           daemon lifecycle and request handling.
  ipc.py              JSON-lines daemon protocol.
  store.py            SQLite persistence and NDJSON event append.
  events.py           persisted event bus with replay and subscribers.
  workspace.py        workspace identity and filesystem layout.
  orchestrator.py     workflow state machine and scheduling decisions.
  worktrees.py        git worktree manager.
  capture.py          structured file, command, diff, and commit event helpers.
  codex_home.py       per-agent CODEX_HOME preparation under the target repo.
  codex_mcp.py        minimal Codex MCP JSONL stdio client.
  project_config.py   repository CXW.toml contract, template generation, validation.
  summaries.py        review, test, risk, and merge summary generation.
  review.py           review record persistence.
  tui.py              prompt-toolkit workspace shell.
  ui.py               Rich terminal rendering.
  agents/
    roles.py          built-in role prompt loading.
    runtime.py        runtime adapter protocol and implementations.
  prompts/            built-in reusable system prompts.
```

Tests live under `tests/`. Phase notes live under `docs/phases/`.

## Architecture Contract

The CLI never owns durable state. It starts or connects to the daemon and sends a
JSON-lines request. The daemon is the single source of truth.

```text
CLI -> Daemon -> State Store / Event Bus / Agent Runtime -> Worktree Manager
```

The state store persists:

- `workspaces`
- `agents`
- `tasks`
- `events`
- `state_transitions`
- `commits`
- `reviews`

Events are also appended to:

```text
~/.cxw/workspaces/<workspace_id>/events.ndjson
```

## Project Configuration Contract

Each orchestrated repository is expected to contain `CXW.toml` at its root. On
first launch, CXW creates a template if the file is missing and waits for the
user to fill it in.

Required content:

- `[workspace].name`
- `[workspace].goal`
- at least one worker entry in `[[agents]]` or legacy `[[roles]]`
- optional `[main_agent]`
- optional `[defaults.codex]`
- at least one worker with role `planner`
- at least one `[[tasks]]`
- every task must reference an existing non-planner agent

Roles use built-in role kinds for now:

```text
planner
frontend-coder
backend-coder
tester
reviewer
```

The configured agents and tasks are the source of truth. Do not add code paths
that recreate hard-coded frontend/backend defaults. `[[roles]]` remains accepted
for backward compatibility; new config examples should use `[[agents]]`.

`[defaults.codex]` and per-agent `[agents.codex]` settings are parsed into
`CodexAgentRuntimeConfig`. The orchestrator prepares a main Codex home even when
the project plan is still a template, and prepares worker Codex homes once the
config is valid.

## Repository-Local Codex Homes

Per-agent homes are created under the target repository:

```text
<repo>/.codex/cxw/main-1
<repo>/.codex/cxw/agents/<agent-name>
```

Each home contains:

- copied `auth.json` when the source `CODEX_HOME` or `~/.codex` has one
- generated `config.toml`
- non-secret `cxw-agent.json`

The manager must never log auth contents. Event payloads may include paths and
`auth_copied`, but not token data.

## Workflow State Machine

Allowed states:

```text
INIT
COLLECT_REQUIREMENTS
PLAN
WAIT_FOR_USER_APPROVAL
CREATE_WORKTREES
DISPATCH
MONITOR
REVIEW
MERGE_PLAN
WAIT_FOR_FINAL_APPROVAL
DONE
FAILED
```

Allowed transitions are defined in `cxw.orchestrator.ALLOWED_TRANSITIONS`.
Every transition must be persisted in `state_transitions` and emitted as an event.

## Event Model

Use `EventBus.publish()` for all user-visible actions. The store assigns a
monotonic workspace-local `sequence`.

An event should include:

- `agent`: the actor, or `orchestrator`.
- `type`: stable event type.
- `message`: concise user-facing line.
- `payload`: structured detail for replay and UI.

Do not put hidden chain-of-thought in events. Use summaries:

- `current_goal`
- `current_action`
- `reasoning_summary`
- `next_action`

## Agent Runtime Extension

Runtime integrations implement:

```python
class AgentRuntime(Protocol):
    async def dispatch(self, agent: AgentRecord, task: TaskRecord) -> None:
        ...
```

Current implementations:

- `LocalDeterministicRuntime`: no external API; useful for tests and dry runs.
- `CodexMcpRuntime`: starts `codex mcp-server`, initializes JSONL MCP, lists
  tools, and calls the real `codex` tool for assigned tasks.
- `OpenAIAgentsRuntime`: optional OpenAI Agents SDK boundary.

Runtime selection order:

1. `CXW_AGENT_RUNTIME` environment override.
2. `cxw <repo> run --runtime <name>` or interactive `/run --runtime <name>`.
3. Explicit `[defaults.codex] runtime = "..."` in `CXW.toml`.
4. `local-deterministic` fallback for older configs.

Supported runtime names:

```text
CXW_AGENT_RUNTIME=local-deterministic
CXW_AGENT_RUNTIME=codex-mcp
CXW_AGENT_RUNTIME=openai-agents
```

Add future runtime adapters behind the same protocol. Keep tool/file/command
events flowing through `EventBus` so attach, replay, and recovery stay consistent.

Codex MCP command discovery:

```text
CXW_CODEX_MCP_COMMAND="codex mcp-server"
CXW_CODEX_BIN=codex
```

The local Codex MCP server currently uses newline-delimited JSON messages over
stdio. `McpStdioClient` also supports `content-length` framing for compatibility
tests.

## Event Capture Helpers

Use `AgentEventCapture` for agent-visible operations:

- `read_text(agent, path)`
- `write_text(agent, path, content)`
- `run_command(agent, args, cwd=...)`
- `capture_git_diff(agent)`
- `record_commit(agent, sha=..., summary=...)`

The helper resolves file and command working directories under the agent's
assigned worktree. If an agent does not have a worktree yet, it uses the repo root.
Paths outside the agent root are rejected.

## Summary Generation

Use `SummaryService.generate()` to produce:

- review summary
- test summary
- risk summary
- merge plan

The service reads persisted state and emits one durable `summary` event. It does
not merge branches or bypass human approval.

## Worktree Rules

`WorktreeManager` enforces:

- one active agent owns exactly one worktree
- branch name is `cxw/<agent-name>`
- worktrees are created under the CXW workspace data root
- an existing worktree path cannot be claimed by another agent

Do not add code paths that let multiple agents write the same worktree.

## Testing Rules

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest -p no:cacheprovider
```

Add tests when changing:

- daemon protocol
- state transitions
- schema writes or reads
- event semantics
- worktree ownership
- backup and recovery behavior
