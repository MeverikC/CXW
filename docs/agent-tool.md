# CXW Agent Tool Contract

This document is for coding agents that call CXW as an external local tool.

CXW is the orchestration control plane for one repository. The caller provides
user intent and final approval; CXW manages workspace state, task records,
events, worktrees, and runtime dispatch.

## Required Flow

1. Run `cxw <repo> config-check --json`.
2. If a template was created, ask the user to complete `CXW.toml`.
3. Run `cxw <repo> status --json` and inspect the snapshot.
4. After the user confirms the plan, run `cxw <repo> run --json`.
5. Observe progress with `logs`, agent attach streams, or `status`.
6. Present summaries to the user before final approval.

Never treat a generated template as an approved plan.

## Repository Files

CXW may create:

```text
CXW.toml
.gitignore
.codex/cxw/main-1/
.codex/cxw/agents/<agent-name>/
```

`.codex/` must stay untracked. CXW adds it to `.gitignore`.

## Project Plan

Preferred shape:

```toml
[workspace]
name = "Project Name"
goal = "User-approved engineering outcome."

[main_agent]
name = "main-1"
instructions = "Plan, schedule, monitor, and delegate approvals."

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
instructions = "Plan the work."

[[agents]]
name = "engineer-1"
role = "backend-coder"
instructions = "Implement the scoped task."

[[tasks]]
title = "Implement feature"
description = "Detailed task for engineer-1."
assigned_agent = "engineer-1"
```

Compatibility: older `[[roles]]` entries still work, but new files should use
`[[agents]]`.

Rules:

- At least one planner worker is required.
- Agent names must be unique and distinct from the main agent name.
- At least one task is required.
- Tasks must reference existing non-planner workers.
- Do not invent frontend/backend agents unless `CXW.toml` defines them.

## JSON Commands

Validate or create the project plan:

```bash
cxw <repo> config-check --json
```

Pass:

- `project_config.valid == true`

Needs user action:

- `project_config.created_template == true`
- `project_config.valid == false`
- `project_config.errors` contains TODO or schema errors

Structured plan commands:

```bash
cxw <repo> plan status --json
cxw <repo> plan init "Project goal" --json
cxw <repo> plan auto "React + FastAPI lottery app" --json
cxw <repo> plan add agent reviewer-1 reviewer "Review implementation branches" --json
cxw <repo> plan add task reviewer-1 "Review implementation" -- "Review generated branches." --json
cxw <repo> plan edit goal "Updated project goal" --json
```

Interactive shell users can run the same surface with `/plan ...`.

Plan command pass condition:

- `ok == true`
- `reply` explains the change or validation result
- `snapshot.project_config.valid` reflects the current plan state

Safety:

- `plan auto` does not overwrite a non-template plan unless `--force` is passed.
- ordinary main-agent chat must not mutate `CXW.toml`; use `plan` commands.

Start or attach to a workspace:

```bash
cxw <repo> --json
```

Pass:

- `ok == true`
- `snapshot.agents` contains the main agent
- `<repo>/.codex/cxw/main-1/config.toml` exists

Run the plan:

```bash
cxw <repo> run --json
```

Pass:

- `ok == true`
- assigned workers have `worktree_path` and `branch`
- events include `worktree_created` and `task_assigned`

Replay events:

```bash
cxw <repo> logs --json
cxw <repo> logs <agent> --json
```

Attach to one agent:

```bash
cxw <repo> <agent> --json
```

This follows the live stream until interrupted.

Generate summaries:

```bash
cxw <repo> summaries --json
cxw <repo> merge-plan --json
```

Pass:

- `summaries.merge_plan.human_approval_required == true`
- no autonomous merge is performed

## Runtime Environment

Default runtime:

```bash
cxw <repo> run --runtime local-deterministic --json
```

Codex MCP runtime:

```bash
cxw <repo> run --json
```

Use `CXW_AGENT_RUNTIME=codex-mcp` only when the caller needs to override a
repository plan that does not explicitly declare `[defaults.codex].runtime`.

Optional overrides:

```bash
CXW_CODEX_BIN=codex
CXW_CODEX_MCP_COMMAND="codex mcp-server"
```

CXW prepares per-agent `CODEX_HOME` directories in the repository. Do not read or
log `auth.json`; only use non-secret metadata from `cxw-agent.json`.

## Safety

- Do not edit another agent's worktree.
- Do not merge branches automatically.
- Do not bypass `WAIT_FOR_USER_APPROVAL` or final human approval.
- Do not expose hidden chain-of-thought in events.
- Do not commit `.codex/` or copied auth files.
