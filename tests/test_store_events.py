from __future__ import annotations

import asyncio
import json

from cxw.events import EventBus
from cxw.models import EventType, WorkspaceRecord
from cxw.store import StateStore
from cxw.workspace import WorkspaceLayout


def test_store_persists_events_to_sqlite_and_ndjson(tmp_path, monkeypatch):
    monkeypatch.setenv("CXW_HOME", str(tmp_path / "cxw-home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    layout = WorkspaceLayout.from_repo(repo)
    store = StateStore(layout)
    store.upsert_workspace(WorkspaceRecord(id=layout.workspace_id, repo_path=str(repo)))
    bus = EventBus(store, layout.workspace_id)

    asyncio.run(
        bus.publish(EventType.COMMAND, agent="backend-1", message="running tests", payload={"ok": True})
    )

    events = store.list_events(layout.workspace_id)
    assert len(events) == 1
    assert events[0].sequence == 1
    assert events[0].agent == "backend-1"
    assert events[0].payload == {"ok": True}

    line = layout.events_path.read_text(encoding="utf-8").strip()
    assert json.loads(line)["type"] == "command"


def test_event_bus_replays_without_following(tmp_path, monkeypatch):
    monkeypatch.setenv("CXW_HOME", str(tmp_path / "cxw-home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    layout = WorkspaceLayout.from_repo(repo)
    store = StateStore(layout)
    store.upsert_workspace(WorkspaceRecord(id=layout.workspace_id, repo_path=str(repo)))
    bus = EventBus(store, layout.workspace_id)

    async def run():
        await bus.publish(EventType.READ_FILE, agent="backend-1", message="reading auth.py")
        return [event async for event in bus.stream(agent="backend-1", follow=False)]

    events = asyncio.run(run())

    assert [event.message for event in events] == ["reading auth.py"]

