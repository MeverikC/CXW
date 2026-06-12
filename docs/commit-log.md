# CXW Commit Log

This file records each complete committed unit of work so the project history can
be reviewed quickly.

## Entries

| Sequence | Commit Message | Functional Unit | Verification |
| --- | --- | --- | --- |
| 000 | `chore: establish cxw baseline` | Established the initial CXW Python package, daemon IPC, SQLite store, event bus, worktree manager, role prompts, CLI, phase notes, and baseline tests. | `python -m pytest -p no:cacheprovider` passed before the next work unit. |
| 001 | `docs: add official cxw guides` | Adds official user, developer, operations, extension roadmap, and commit ledger documentation. | Documentation-only; package metadata and test suite checked before commit. |
| 002 | `feat: add daemon management commands` | Adds workspace listing, daemon health, daemon shutdown, and workspace info commands without forcing management checks to start stopped daemons. | Full pytest suite and CLI help checked before commit. |
| 003 | `feat: add workspace backup restore` | Adds portable workspace backup archives, safe restore without overwriting existing state, path-aware metadata, and workspace id rewriting for restored SQLite/NDJSON state. | Full pytest suite checked before commit. |
| 004 | `feat: add agent event capture helpers` | Adds reusable helpers for agent-scoped file reads/writes, argv-based command execution, git diff capture, and commit event persistence. | Full pytest suite checked before commit. |
| 005 | `feat: add workflow summary generation` | Adds review, test, risk, and merge summary generation through daemon/CLI while preserving human final approval and no-autonomous-merge policy. | Full pytest suite and CLI smoke checks completed before commit. |
| 006 | `fix: improve workspace list empty state` | Makes `cxw workspaces` show a visible empty-state row when no persisted workspaces exist. | Full pytest suite and CLI smoke checks completed before commit. |
