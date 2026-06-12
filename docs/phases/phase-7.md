# Phase 7: Recovery and Persistence

Implemented:

- Daemon startup reuses persisted workspace state.
- CLI commands start or reconnect to the daemon.
- `resume` publishes a recovery event without losing state.
- State transitions are explicit and persisted.
- Recovery now re-evaluates completed `MONITOR`, `REVIEW`, and `MERGE_PLAN` states and
  advances them through persisted review records, summary generation, and final approval wait.
- Task dispatch status is persisted so recovery can distinguish assigned dry-run tasks from
  completed runtime tasks.

Migration notes:

- Daemon endpoint metadata is runtime-only and can be regenerated.
- SQLite and NDJSON logs are the durable recovery sources.
- A workspace that already has completed tasks but no review records will create conservative
  `request_changes` review-gate records on resume.
