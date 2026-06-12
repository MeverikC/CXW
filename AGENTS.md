# CXW Project Constitution

## Mission

Build a production-grade local-first multi-agent orchestration platform called **CXW**.

CXW is not a wrapper around Codex.

CXW is a workspace-centric orchestration system that:

- manages multiple coding agents
- manages git worktrees
- coordinates task execution
- provides real-time visibility
- provides auditability
- provides replayability
- provides deterministic workflow execution

The user should experience CXW as:

"Operating a software engineering team from the terminal."

------

# Core Product Vision

The user enters:

```bash
cxw /path/to/repo
```

and launches a persistent workspace.

A workspace contains:

- a main orchestrator agent
- multiple worker agents
- worktrees
- task assignments
- event streams
- execution history
- audit logs

The orchestrator acts like an engineering manager.

Worker agents act like engineers.

Reviewer agents act like senior reviewers.

Tester agents act like QA engineers.

The user acts as the final approver.

------

# Critical Design Principle

DO NOT build a chat application.

DO NOT build a multi-terminal wrapper.

DO NOT build a simple Codex launcher.

Build an orchestration platform.

The orchestrator owns:

- planning
- scheduling
- task assignment
- retries
- reviews
- state transitions

Worker agents own:

- implementation

Nothing else.

------

# Workspace Identity

A workspace is uniquely identified by:

```text
absolute repository path
```

Generate:

```text
workspace_id = sha256(repo_path)
```

Workspace data must be stored under:

```text
~/.cxw/workspaces/<workspace_id>
```

------

# Mandatory Architecture

CXW must contain:

```text
CLI
Daemon
State Store
Event Bus
Agent Runtime
Worktree Manager
Review System
Persistence Layer
```

Architecture:

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

------

# Daemon Requirements

A daemon is mandatory.

Reason:

Multiple terminals must observe the same workspace.

Commands:

```bash
cxw repo
cxw repo status
cxw repo frontend-1
cxw repo logs frontend-1
cxw repo stop frontend-1
cxw repo resume
```

All commands communicate with the daemon.

The daemon is the single source of truth.

------

# Event System

Every significant action must become an event.

Examples:

```json
{
  "agent":"backend-1",
  "type":"read_file"
}
{
  "agent":"backend-1",
  "type":"write_file"
}
{
  "agent":"backend-1",
  "type":"tool_call"
}
{
  "agent":"backend-1",
  "type":"command"
}
{
  "agent":"backend-1",
  "type":"commit"
}
{
  "agent":"backend-1",
  "type":"failed"
}
```

Events must be:

- streamable
- replayable
- persisted

Storage format:

```text
NDJSON
```

and

```text
SQLite
```

------

# Real-Time Visibility

The user must be able to attach to any agent.

Example:

```bash
cxw repo backend-1
```

Expected output:

```text
[10:00] reading auth.py
[10:01] editing auth.py
[10:02] running tests
[10:05] commit created
```

The experience should resemble:

```text
tail -f
```

for agent activity.

------

# Agent Transparency

Expose:

- plans
- actions
- tool calls
- commands
- file reads
- file writes
- diffs
- commits
- summaries

Do NOT expose hidden chain-of-thought.

Instead expose:

```text
current goal
current action
reasoning summary
next action
```

------

# Worktree Rules

Each active agent owns exactly one worktree.

Constraint:

```text
1 agent <-> 1 worktree
```

Never allow:

```text
multiple agents writing the same worktree
```

Worktrees are automatically generated.

Example:

```text
worktrees/frontend-1
worktrees/backend-1
worktrees/tester-1
```

Branch naming:

```text
cxw/<agent-name>
```

------

# Built-In Roles

Version 1 must include:

```text
planner
frontend-coder
backend-coder
tester
reviewer
```

Roles are implemented as reusable system prompts.

Future roles must be pluggable.

------

# Orchestrator Agent

The orchestrator never performs implementation.

Its responsibilities:

- planning
- scheduling
- monitoring
- reassignment
- retries
- review triggering
- merge preparation

The orchestrator is a state machine.

------

# Workflow State Machine

Required states:

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

State transitions must be explicit and persisted.

------

# Failure Handling

If an agent fails:

```text
FAILED
```

Orchestrator must decide:

```text
retry
reassign
escalate
ask_user
```

Never silently terminate.

------

# Review System

Every implementation branch must be reviewed.

Flow:

```text
implementer
    ->
reviewer
    ->
human approval
```

No direct merge.

Reviewer outputs:

```text
approve

or

request_changes
```

with rationale.

------

# Merge Policy

Version 1:

Human approval required.

No autonomous merge.

The system may generate:

```text
merge plan
risk summary
review summary
test summary
```

The user executes final approval.

------

# User Interface

Main Window:

```text
Workspace
Plan
Agent Status Table
Recent Events
Orchestrator Decisions
```

Agent Window:

```text
Agent Timeline
Tool Calls
File Operations
Commands
Commit Information
```

------

# Persistence

Required:

```text
SQLite
```

Tables:

```text
workspaces
agents
tasks
events
state_transitions
commits
reviews
```

The system must recover after restart.

------

# Technology Stack

Python

OpenAI Agents SDK

Codex MCP

SQLite

Rich

Typer

Pydantic

Asyncio

Git Worktrees

Unix Domain Sockets

Avoid unnecessary frameworks.

------

# MVP Definition

The project is complete when:

- workspace creation works
- daemon works
- multi-agent execution works
- worktree isolation works
- event streaming works
- agent attach works
- reviewer works
- persistence works
- restart recovery works

Only then proceed to advanced features.

------

# Non-Goals

Do not build:

- web frontend
- cloud service
- distributed cluster
- kubernetes deployment
- multi-machine execution

Build a robust local-first orchestration platform first.

------

# Success Criteria

A user should be able to:

```bash
cxw ~/repo
```

approve a plan,

watch multiple agents work in real time,

attach to any agent,

observe all actions,

review results,

and manage a complete engineering workflow entirely from the terminal.





# Implementation strategy:

Do NOT generate the entire project at once.

Work in phases.

Phase 1:
Project skeleton + daemon + CLI.

Phase 2:
State store + event bus.

Phase 3:
Worktree manager.

Phase 4:
Agents SDK integration.

Phase 5:
Real-time attach UI.

Phase 6:
Reviewer workflow.

Phase 7:
Recovery and persistence.

At the end of each phase:
- generate architecture diagram
- generate tests
- generate migration notes
- wait for approval before continuing