# CXW Extension Roadmap

This is the prioritized implementation roadmap after the baseline.

## Priority 1: Official Documentation

Status: implemented.

Deliverables:

- user guide
- developer guide
- operations guide
- extension roadmap
- commit ledger

## Priority 2: Daemon Management

Status: implemented.

Add commands for:

- listing known workspaces
- daemon health checks
- daemon shutdown
- workspace metadata inspection

Why this matters:

The daemon is mandatory and must be observable as a first-class local service.

## Priority 3: Workspace Backup And Restore

Status: implemented.

Add commands for:

- creating a portable backup archive
- restoring an archive to a repo path
- storing original and restored repo path metadata
- excluding transient endpoint files

Why this matters:

Workspace ids depend on absolute repo paths, so migration needs explicit tooling.

## Priority 4: Event Capture Helpers

Status: implemented.

Add reusable APIs for:

- command execution events
- file read/write events
- git diff events
- commit events

Why this matters:

Agent transparency depends on structured event capture, not ad hoc log lines.

## Priority 5: Review, Test, Risk, And Merge Summaries

Status: implemented.

Add generated summaries for:

- review status
- test results
- risk notes
- merge plan

Why this matters:

Human approval needs a compact audit trail before merge.

## Later Work

- Full Codex MCP worker runtime.
- Pluggable role packages.
- Task retry and reassignment policy engine.
- Rich live dashboard refresh.
- Schema migrations beyond version 1.
- Durable job recovery for in-flight agent tasks.
