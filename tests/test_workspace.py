from __future__ import annotations

import hashlib

from cxw.workspace import WorkspaceLayout, workspace_id_for_repo


def test_workspace_id_uses_absolute_repo_path(tmp_path, monkeypatch):
    monkeypatch.setenv("CXW_HOME", str(tmp_path / "cxw-home"))
    repo = tmp_path / "repo"
    repo.mkdir()

    expected = hashlib.sha256(str(repo.resolve()).encode("utf-8")).hexdigest()

    assert workspace_id_for_repo(repo) == expected
    layout = WorkspaceLayout.from_repo(repo)
    assert layout.workspace_id == expected
    assert layout.root == tmp_path / "cxw-home" / "workspaces" / expected


def test_layout_ensure_creates_workspace_directories(tmp_path, monkeypatch):
    monkeypatch.setenv("CXW_HOME", str(tmp_path / "cxw-home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    layout = WorkspaceLayout.from_repo(repo)

    layout.ensure()

    assert layout.root.is_dir()
    assert layout.run_dir.is_dir()
    assert layout.logs_dir.is_dir()
    assert layout.worktrees_dir.is_dir()

