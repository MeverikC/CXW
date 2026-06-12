# Phase 1: Project Skeleton, Daemon, CLI

Implemented:

- Python package skeleton under `src/cxw`.
- `pyproject.toml` with Typer, Rich, and Pydantic dependencies.
- Typer CLI supporting `cxw repo`, `status`, `plan`, `run`, `logs`, `stop`, `resume`, dynamic agent attach, legacy `approve-plan`, and `final-approve`.
- Daemon process entry point with JSON-lines IPC.
- Architecture diagram in `docs/architecture.md`.

Migration notes:

- Install with `python -m pip install -e ".[dev]"`.
- Existing workspaces are not migrated because this is schema version 1.
