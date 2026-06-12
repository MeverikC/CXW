# Phase 2: State Store and Event Bus

Implemented:

- SQLite schema for workspaces, agents, tasks, events, transitions, commits, and reviews.
- Append-only `events.ndjson`.
- Persisted event stream with replay and realtime subscribers.
- Tests cover event persistence and replay.

Migration notes:

- SQLite `PRAGMA user_version` is set to `1`.
- Future migrations should add explicit schema migration functions before raising the user version.

