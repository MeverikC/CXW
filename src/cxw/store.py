from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

from cxw.models import (
    AgentRecord,
    AgentStatus,
    CommitRecord,
    EventRecord,
    ReviewRecord,
    StateTransitionRecord,
    TaskRecord,
    WorkspaceRecord,
    WorkflowState,
    utc_now,
)
from cxw.serialization import dumps_json
from cxw.workspace import WorkspaceLayout

SCHEMA_VERSION = 1


def _dt(value: datetime | str) -> str:
    return value.isoformat() if isinstance(value, datetime) else value


def _value(value: Any) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


def _loads(value: str | bytes | None) -> dict[str, Any]:
    if not value:
        return {}
    loaded = json.loads(value)
    return loaded if isinstance(loaded, dict) else {}


class StateStore:
    """SQLite persistence layer plus append-only NDJSON event log."""

    def __init__(self, layout: WorkspaceLayout):
        self.layout = layout
        self.layout.ensure()
        self._conn = sqlite3.connect(self.layout.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self.init_schema()

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def init_schema(self) -> None:
        with self.tx() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;

                CREATE TABLE IF NOT EXISTS workspaces (
                    id TEXT PRIMARY KEY,
                    repo_path TEXT NOT NULL UNIQUE,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    status TEXT NOT NULL,
                    worktree_path TEXT,
                    branch TEXT,
                    current_goal TEXT,
                    current_action TEXT,
                    reasoning_summary TEXT,
                    next_action TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(workspace_id, name),
                    UNIQUE(workspace_id, worktree_path),
                    FOREIGN KEY(workspace_id) REFERENCES workspaces(id)
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL,
                    assigned_agent TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(workspace_id) REFERENCES workspaces(id)
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    ts TEXT NOT NULL,
                    agent TEXT,
                    type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    UNIQUE(workspace_id, sequence),
                    FOREIGN KEY(workspace_id) REFERENCES workspaces(id)
                );

                CREATE TABLE IF NOT EXISTS state_transitions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace_id TEXT NOT NULL,
                    from_state TEXT NOT NULL,
                    to_state TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    ts TEXT NOT NULL,
                    FOREIGN KEY(workspace_id) REFERENCES workspaces(id)
                );

                CREATE TABLE IF NOT EXISTS commits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace_id TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    branch TEXT NOT NULL,
                    sha TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    ts TEXT NOT NULL,
                    FOREIGN KEY(workspace_id) REFERENCES workspaces(id)
                );

                CREATE TABLE IF NOT EXISTS reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace_id TEXT NOT NULL,
                    reviewer TEXT NOT NULL,
                    implementer TEXT NOT NULL,
                    branch TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    ts TEXT NOT NULL,
                    FOREIGN KEY(workspace_id) REFERENCES workspaces(id)
                );
                """
            )
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def upsert_workspace(self, record: WorkspaceRecord) -> WorkspaceRecord:
        with self.tx() as conn:
            conn.execute(
                """
                INSERT INTO workspaces (id, repo_path, state, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    repo_path=excluded.repo_path,
                    state=excluded.state,
                    updated_at=excluded.updated_at
                """,
                (
                    record.id,
                    record.repo_path,
                    _value(record.state),
                    _dt(record.created_at),
                    _dt(record.updated_at),
                ),
            )
        return record

    def get_workspace(self, workspace_id: str) -> WorkspaceRecord | None:
        row = self._conn.execute("SELECT * FROM workspaces WHERE id=?", (workspace_id,)).fetchone()
        if row is None:
            return None
        return WorkspaceRecord(
            id=row["id"],
            repo_path=row["repo_path"],
            state=row["state"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def update_workspace_state(self, workspace_id: str, state: WorkflowState) -> None:
        with self.tx() as conn:
            conn.execute(
                "UPDATE workspaces SET state=?, updated_at=? WHERE id=?",
                (_value(state), _dt(utc_now()), workspace_id),
            )

    def upsert_agent(self, record: AgentRecord) -> AgentRecord:
        with self.tx() as conn:
            cursor = conn.execute(
                """
                INSERT INTO agents (
                    workspace_id, name, role, status, worktree_path, branch,
                    current_goal, current_action, reasoning_summary, next_action,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, name) DO UPDATE SET
                    role=excluded.role,
                    status=excluded.status,
                    worktree_path=COALESCE(excluded.worktree_path, agents.worktree_path),
                    branch=COALESCE(excluded.branch, agents.branch),
                    current_goal=excluded.current_goal,
                    current_action=excluded.current_action,
                    reasoning_summary=excluded.reasoning_summary,
                    next_action=excluded.next_action,
                    updated_at=excluded.updated_at
                RETURNING id
                """,
                (
                    record.workspace_id,
                    record.name,
                    _value(record.role),
                    _value(record.status),
                    record.worktree_path,
                    record.branch,
                    record.current_goal,
                    record.current_action,
                    record.reasoning_summary,
                    record.next_action,
                    _dt(record.created_at),
                    _dt(record.updated_at),
                ),
            )
            record.id = int(cursor.fetchone()["id"])
        return record

    def get_agent(self, workspace_id: str, name: str) -> AgentRecord | None:
        row = self._conn.execute(
            "SELECT * FROM agents WHERE workspace_id=? AND name=?", (workspace_id, name)
        ).fetchone()
        return self._agent_from_row(row) if row else None

    def list_agents(self, workspace_id: str) -> list[AgentRecord]:
        rows = self._conn.execute(
            "SELECT * FROM agents WHERE workspace_id=? ORDER BY name", (workspace_id,)
        ).fetchall()
        return [self._agent_from_row(row) for row in rows]

    def set_agent_status(self, workspace_id: str, name: str, status: AgentStatus) -> None:
        with self.tx() as conn:
            conn.execute(
                "UPDATE agents SET status=?, updated_at=? WHERE workspace_id=? AND name=?",
                (_value(status), _dt(utc_now()), workspace_id, name),
            )

    def update_agent_worktree(
        self, workspace_id: str, name: str, worktree_path: Path, branch: str
    ) -> None:
        with self.tx() as conn:
            conn.execute(
                """
                UPDATE agents
                SET worktree_path=?, branch=?, updated_at=?
                WHERE workspace_id=? AND name=?
                """,
                (str(worktree_path), branch, _dt(utc_now()), workspace_id, name),
            )

    def update_agent_transparency(
        self,
        workspace_id: str,
        name: str,
        *,
        current_goal: str | None = None,
        current_action: str | None = None,
        reasoning_summary: str | None = None,
        next_action: str | None = None,
    ) -> None:
        with self.tx() as conn:
            conn.execute(
                """
                UPDATE agents
                SET current_goal=?, current_action=?, reasoning_summary=?, next_action=?, updated_at=?
                WHERE workspace_id=? AND name=?
                """,
                (
                    current_goal,
                    current_action,
                    reasoning_summary,
                    next_action,
                    _dt(utc_now()),
                    workspace_id,
                    name,
                ),
            )

    def create_task(self, record: TaskRecord) -> TaskRecord:
        with self.tx() as conn:
            cursor = conn.execute(
                """
                INSERT INTO tasks (
                    workspace_id, title, description, status, assigned_agent, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.workspace_id,
                    record.title,
                    record.description,
                    _value(record.status),
                    record.assigned_agent,
                    _dt(record.created_at),
                    _dt(record.updated_at),
                ),
            )
            record.id = int(cursor.lastrowid)
        return record

    def list_tasks(self, workspace_id: str) -> list[TaskRecord]:
        rows = self._conn.execute(
            "SELECT * FROM tasks WHERE workspace_id=? ORDER BY id", (workspace_id,)
        ).fetchall()
        return [self._task_from_row(row) for row in rows]

    def get_task(self, task_id: int) -> TaskRecord | None:
        row = self._conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return self._task_from_row(row) if row else None

    def update_task(
        self,
        task_id: int,
        *,
        title: str | None = None,
        description: str | None = None,
        status: TaskStatus | None = None,
        assigned_agent: str | None = None,
    ) -> None:
        updates = []
        params = []
        if title is not None:
            updates.append("title=?")
            params.append(title)
        if description is not None:
            updates.append("description=?")
            params.append(description)
        if status is not None:
            updates.append("status=?")
            params.append(_value(status))
        if assigned_agent is not None:
            updates.append("assigned_agent=?")
            params.append(assigned_agent)
        if not updates:
            return
        updates.append("updated_at=?")
        params.append(_dt(utc_now()))
        params.append(task_id)
        with self.tx() as conn:
            conn.execute(
                f"UPDATE tasks SET {', '.join(updates)} WHERE id=?",
                tuple(params),
            )

    def append_event(self, record: EventRecord) -> EventRecord:
        with self.tx() as conn:
            sequence = conn.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 AS next FROM events WHERE workspace_id=?",
                (record.workspace_id,),
            ).fetchone()["next"]
            cursor = conn.execute(
                """
                INSERT INTO events (workspace_id, sequence, ts, agent, type, message, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.workspace_id,
                    int(sequence),
                    _dt(record.ts),
                    record.agent,
                    _value(record.type),
                    record.message,
                    dumps_json(record.payload),
                ),
            )
            record.id = int(cursor.lastrowid)
            record.sequence = int(sequence)
            self._append_ndjson(record)
        return record

    def list_events(
        self,
        workspace_id: str,
        *,
        agent: str | None = None,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> list[EventRecord]:
        params: list[Any] = [workspace_id, after_sequence]
        where = "workspace_id=? AND sequence>?"
        if agent is not None:
            where += " AND agent=?"
            params.append(agent)
        limit_clause = ""
        if limit is not None:
            limit_clause = " LIMIT ?"
            params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM events WHERE {where} ORDER BY sequence{limit_clause}",
            params,
        ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def count_rows(self, table: str, workspace_id: str | None = None) -> int:
        allowed = {
            "workspaces",
            "agents",
            "tasks",
            "events",
            "state_transitions",
            "commits",
            "reviews",
        }
        if table not in allowed:
            raise ValueError(f"unsupported table for count: {table}")
        if workspace_id is None or table == "workspaces":
            return int(self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        return int(
            self._conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE workspace_id=?", (workspace_id,)
            ).fetchone()[0]
        )

    def append_transition(self, record: StateTransitionRecord) -> StateTransitionRecord:
        with self.tx() as conn:
            cursor = conn.execute(
                """
                INSERT INTO state_transitions (workspace_id, from_state, to_state, reason, ts)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    record.workspace_id,
                    _value(record.from_state),
                    _value(record.to_state),
                    record.reason,
                    _dt(record.ts),
                ),
            )
            record.id = int(cursor.lastrowid)
        return record

    def list_transitions(self, workspace_id: str) -> list[StateTransitionRecord]:
        rows = self._conn.execute(
            "SELECT * FROM state_transitions WHERE workspace_id=? ORDER BY id", (workspace_id,)
        ).fetchall()
        return [self._transition_from_row(row) for row in rows]

    def append_commit(self, record: CommitRecord) -> CommitRecord:
        with self.tx() as conn:
            cursor = conn.execute(
                """
                INSERT INTO commits (workspace_id, agent, branch, sha, summary, ts)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    record.workspace_id,
                    record.agent,
                    record.branch,
                    record.sha,
                    record.summary,
                    _dt(record.ts),
                ),
            )
            record.id = int(cursor.lastrowid)
        return record

    def list_commits(self, workspace_id: str) -> list[CommitRecord]:
        rows = self._conn.execute(
            "SELECT * FROM commits WHERE workspace_id=? ORDER BY id", (workspace_id,)
        ).fetchall()
        return [self._commit_from_row(row) for row in rows]

    def append_review(self, record: ReviewRecord) -> ReviewRecord:
        with self.tx() as conn:
            cursor = conn.execute(
                """
                INSERT INTO reviews (workspace_id, reviewer, implementer, branch, decision, rationale, ts)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.workspace_id,
                    record.reviewer,
                    record.implementer,
                    record.branch,
                    _value(record.decision),
                    record.rationale,
                    _dt(record.ts),
                ),
            )
            record.id = int(cursor.lastrowid)
        return record

    def list_reviews(self, workspace_id: str) -> list[ReviewRecord]:
        rows = self._conn.execute(
            "SELECT * FROM reviews WHERE workspace_id=? ORDER BY id", (workspace_id,)
        ).fetchall()
        return [self._review_from_row(row) for row in rows]

    def _append_ndjson(self, record: EventRecord) -> None:
        self.layout.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.layout.events_path.open("a", encoding="utf-8") as file:
            file.write(dumps_json(record) + "\n")

    @staticmethod
    def _agent_from_row(row: sqlite3.Row) -> AgentRecord:
        return AgentRecord(
            id=row["id"],
            workspace_id=row["workspace_id"],
            name=row["name"],
            role=row["role"],
            status=row["status"],
            worktree_path=row["worktree_path"],
            branch=row["branch"],
            current_goal=row["current_goal"],
            current_action=row["current_action"],
            reasoning_summary=row["reasoning_summary"],
            next_action=row["next_action"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _task_from_row(row: sqlite3.Row) -> TaskRecord:
        return TaskRecord(
            id=row["id"],
            workspace_id=row["workspace_id"],
            title=row["title"],
            description=row["description"],
            status=row["status"],
            assigned_agent=row["assigned_agent"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> EventRecord:
        return EventRecord(
            id=row["id"],
            workspace_id=row["workspace_id"],
            sequence=row["sequence"],
            ts=row["ts"],
            agent=row["agent"],
            type=row["type"],
            message=row["message"],
            payload=_loads(row["payload"]),
        )

    @staticmethod
    def _transition_from_row(row: sqlite3.Row) -> StateTransitionRecord:
        return StateTransitionRecord(
            id=row["id"],
            workspace_id=row["workspace_id"],
            from_state=row["from_state"],
            to_state=row["to_state"],
            reason=row["reason"],
            ts=row["ts"],
        )

    @staticmethod
    def _commit_from_row(row: sqlite3.Row) -> CommitRecord:
        return CommitRecord(
            id=row["id"],
            workspace_id=row["workspace_id"],
            agent=row["agent"],
            branch=row["branch"],
            sha=row["sha"],
            summary=row["summary"],
            ts=row["ts"],
        )

    @staticmethod
    def _review_from_row(row: sqlite3.Row) -> ReviewRecord:
        return ReviewRecord(
            id=row["id"],
            workspace_id=row["workspace_id"],
            reviewer=row["reviewer"],
            implementer=row["implementer"],
            branch=row["branch"],
            decision=row["decision"],
            rationale=row["rationale"],
            ts=row["ts"],
        )
