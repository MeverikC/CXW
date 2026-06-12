from __future__ import annotations

import asyncio

from cxw.models import WorkspaceRecord
from cxw.registry import list_workspace_summaries
from cxw.store import StateStore
from cxw.workspace import WorkspaceLayout


def test_registry_lists_persisted_workspaces(tmp_path, monkeypatch):
    monkeypatch.setenv("CXW_HOME", str(tmp_path / "cxw-home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    layout = WorkspaceLayout.from_repo(repo)
    store = StateStore(layout)
    store.upsert_workspace(WorkspaceRecord(id=layout.workspace_id, repo_path=str(repo)))
    store.close()

    summaries = asyncio.run(list_workspace_summaries(check_daemons=False))

    assert len(summaries) == 1
    assert summaries[0].workspace_id == layout.workspace_id
    assert summaries[0].repo_path == str(repo)
    assert summaries[0].daemon_running is False

