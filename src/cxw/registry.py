from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from cxw.ipc import Endpoint, ping
from cxw.workspace import cxw_home


@dataclass(frozen=True)
class WorkspaceSummary:
    workspace_id: str
    repo_path: str | None
    state: str | None
    root: Path
    db_path: Path
    events_path: Path
    endpoint_path: Path
    daemon_running: bool = False
    event_count: int = 0
    agent_count: int = 0


def workspace_roots() -> list[Path]:
    root = cxw_home() / "workspaces"
    if not root.exists():
        return []
    return sorted(path for path in root.iterdir() if path.is_dir())


async def list_workspace_summaries(*, check_daemons: bool = True) -> list[WorkspaceSummary]:
    summaries: list[WorkspaceSummary] = []
    for root in workspace_roots():
        summaries.append(await read_workspace_summary(root, check_daemon=check_daemons))
    return summaries


async def read_workspace_summary(root: Path, *, check_daemon: bool = True) -> WorkspaceSummary:
    db_path = root / "state.sqlite3"
    events_path = root / "events.ndjson"
    endpoint_path = root / "run" / "endpoint.json"
    repo_path: str | None = None
    state: str | None = None
    event_count = 0
    agent_count = 0

    if db_path.exists():
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                workspace = conn.execute("SELECT * FROM workspaces LIMIT 1").fetchone()
                if workspace:
                    repo_path = workspace["repo_path"]
                    state = workspace["state"]
                event_count = int(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])
                agent_count = int(conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0])
        except sqlite3.Error:
            state = "unreadable"

    daemon_running = False
    if check_daemon:
        endpoint = read_endpoint_file(endpoint_path)
        daemon_running = bool(endpoint and await ping(endpoint))

    return WorkspaceSummary(
        workspace_id=root.name,
        repo_path=repo_path,
        state=state,
        root=root,
        db_path=db_path,
        events_path=events_path,
        endpoint_path=endpoint_path,
        daemon_running=daemon_running,
        event_count=event_count,
        agent_count=agent_count,
    )


def read_endpoint_file(path: Path) -> Endpoint | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return Endpoint.from_dict(raw)
    except (OSError, ValueError, KeyError, TypeError):
        return None

