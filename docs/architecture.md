# CXW Architecture

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

## Current Modules

- `cxw.cli`: Typer command entry point and Rich terminal rendering.
- `cxw.daemon`: daemon lifecycle, request handling, daemon-owned snapshots.
- `cxw.ipc`: JSON-lines daemon protocol over Unix sockets or local TCP fallback.
- `cxw.store`: SQLite persistence and append-only NDJSON event log.
- `cxw.events`: persisted event publishing plus realtime subscribers.
- `cxw.orchestrator`: explicit workflow state machine and orchestration decisions.
- `cxw.worktrees`: one-agent-to-one-worktree git worktree manager.
- `cxw.agents`: role prompts and runtime adapter boundary.
- `cxw.review`: reviewer decision persistence.

## Persistence

SQLite tables:

```text
workspaces
agents
tasks
events
state_transitions
commits
reviews
```

Events are also appended to `events.ndjson` for replay and audit export.

