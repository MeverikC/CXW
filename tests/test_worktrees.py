from __future__ import annotations

import shutil
import subprocess

import pytest

from cxw.events import EventBus
from cxw.models import AgentRecord, Role, WorkspaceRecord
from cxw.store import StateStore
from cxw.workspace import WorkspaceLayout
from cxw.worktrees import WorktreeManager


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_worktree_manager_creates_isolated_agent_worktree(tmp_path, monkeypatch):
    monkeypatch.setenv("CXW_HOME", str(tmp_path / "cxw-home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "cxw@example.test")
    _git(repo, "config", "user.name", "CXW Test")
    (repo / "README.md").write_text("# repo\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")

    layout = WorkspaceLayout.from_repo(repo)
    store = StateStore(layout)
    store.upsert_workspace(WorkspaceRecord(id=layout.workspace_id, repo_path=str(repo)))
    store.upsert_agent(
        AgentRecord(workspace_id=layout.workspace_id, name="backend-1", role=Role.BACKEND_CODER)
    )
    manager = WorktreeManager(layout, store, EventBus(store, layout.workspace_id))

    import asyncio

    worktree = asyncio.run(manager.ensure_agent_worktree("backend-1"))

    assert worktree.exists()
    agent = store.get_agent(layout.workspace_id, "backend-1")
    assert agent is not None
    assert agent.branch == "cxw/backend-1"
    assert agent.worktree_path == str(worktree)

