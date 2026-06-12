from __future__ import annotations

import json

import pytest

from cxw.backup import create_workspace_backup, restore_workspace_backup
from cxw.models import EventRecord, EventType, WorkspaceRecord
from cxw.store import StateStore
from cxw.workspace import WorkspaceLayout


def test_workspace_backup_and_restore_rewrites_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("CXW_HOME", str(tmp_path / "cxw-home"))
    source_repo = tmp_path / "source"
    target_repo = tmp_path / "target"
    source_repo.mkdir()
    target_repo.mkdir()

    source_layout = WorkspaceLayout.from_repo(source_repo)
    store = StateStore(source_layout)
    store.upsert_workspace(
        WorkspaceRecord(id=source_layout.workspace_id, repo_path=str(source_layout.repo_path))
    )
    store.append_event(
        EventRecord(
            workspace_id=source_layout.workspace_id,
            agent="backend-1",
            type=EventType.COMMAND,
            message="ran tests",
        )
    )
    source_layout.endpoint_path.parent.mkdir(parents=True, exist_ok=True)
    source_layout.endpoint_path.write_text("{}", encoding="utf-8")
    store.close()

    archive = tmp_path / "workspace.cxw.zip"
    backup = create_workspace_backup(source_repo, archive)
    restore = restore_workspace_backup(backup.archive_path, target_repo)
    target_layout = WorkspaceLayout.from_repo(target_repo)
    restored_store = StateStore(target_layout)

    workspace = restored_store.get_workspace(target_layout.workspace_id)
    events = restored_store.list_events(target_layout.workspace_id)
    restored_store.close()

    assert backup.file_count >= 2
    assert restore.target_workspace_id == target_layout.workspace_id
    assert workspace is not None
    assert workspace.repo_path == str(target_layout.repo_path)
    assert len(events) == 1
    assert events[0].workspace_id == target_layout.workspace_id
    assert not target_layout.endpoint_path.exists()
    assert (target_layout.root / "restore.json").exists()

    ndjson = target_layout.events_path.read_text(encoding="utf-8").strip()
    assert json.loads(ndjson)["workspace_id"] == target_layout.workspace_id


def test_restore_refuses_existing_workspace_files(tmp_path, monkeypatch):
    monkeypatch.setenv("CXW_HOME", str(tmp_path / "cxw-home"))
    source_repo = tmp_path / "source"
    target_repo = tmp_path / "target"
    source_repo.mkdir()
    target_repo.mkdir()

    source_layout = WorkspaceLayout.from_repo(source_repo)
    store = StateStore(source_layout)
    store.upsert_workspace(
        WorkspaceRecord(id=source_layout.workspace_id, repo_path=str(source_layout.repo_path))
    )
    store.close()
    backup = create_workspace_backup(source_repo, tmp_path / "workspace.cxw.zip")

    target_layout = WorkspaceLayout.from_repo(target_repo)
    target_layout.ensure()
    (target_layout.root / "existing.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(Exception, match="already contains files"):
        restore_workspace_backup(backup.archive_path, target_repo)

    assert (target_layout.root / "existing.txt").read_text(encoding="utf-8") == "keep"

