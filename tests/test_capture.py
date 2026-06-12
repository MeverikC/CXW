from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys

import pytest

from cxw.capture import AgentEventCapture
from cxw.events import EventBus
from cxw.models import AgentRecord, Role, WorkspaceRecord
from cxw.store import StateStore
from cxw.workspace import WorkspaceLayout


def test_capture_records_file_and_command_events(tmp_path, monkeypatch):
    monkeypatch.setenv("CXW_HOME", str(tmp_path / "cxw-home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    layout = WorkspaceLayout.from_repo(repo)
    store = StateStore(layout)
    store.upsert_workspace(WorkspaceRecord(id=layout.workspace_id, repo_path=str(repo)))
    store.upsert_agent(
        AgentRecord(
            workspace_id=layout.workspace_id,
            name="backend-1",
            role=Role.BACKEND_CODER,
            worktree_path=str(repo),
        )
    )
    capture = AgentEventCapture(layout, store, EventBus(store, layout.workspace_id))

    async def run():
        await capture.write_text("backend-1", "src/app.py", "print('ok')\n")
        content = await capture.read_text("backend-1", "src/app.py")
        command = await capture.run_command(
            "backend-1",
            [sys.executable, "-c", "print('hello')"],
            cwd=".",
        )
        return content, command

    content, command = asyncio.run(run())
    events = store.list_events(layout.workspace_id)

    assert content == "print('ok')\n"
    assert command.returncode == 0
    assert [event.type for event in events] == ["write_file", "read_file", "command"]
    assert events[-1].payload["stdout_tail"].strip() == "hello"


def test_capture_rejects_paths_outside_agent_root(tmp_path, monkeypatch):
    monkeypatch.setenv("CXW_HOME", str(tmp_path / "cxw-home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    layout = WorkspaceLayout.from_repo(repo)
    store = StateStore(layout)
    store.upsert_workspace(WorkspaceRecord(id=layout.workspace_id, repo_path=str(repo)))
    store.upsert_agent(
        AgentRecord(
            workspace_id=layout.workspace_id,
            name="backend-1",
            role=Role.BACKEND_CODER,
            worktree_path=str(repo),
        )
    )
    capture = AgentEventCapture(layout, store, EventBus(store, layout.workspace_id))

    with pytest.raises(Exception, match="outside agent root"):
        asyncio.run(capture.read_text("backend-1", tmp_path / "outside.txt"))


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_capture_records_diff_and_commit(tmp_path, monkeypatch):
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
        AgentRecord(
            workspace_id=layout.workspace_id,
            name="backend-1",
            role=Role.BACKEND_CODER,
            worktree_path=str(repo),
            branch="master",
        )
    )
    capture = AgentEventCapture(layout, store, EventBus(store, layout.workspace_id))

    async def run():
        await capture.write_text("backend-1", "feature.txt", "done\n")
        diff = await capture.capture_git_diff("backend-1")
        _git(repo, "add", "feature.txt")
        _git(repo, "commit", "-m", "feature")
        commit = await capture.record_commit("backend-1", summary="feature")
        return diff, commit

    diff, commit = asyncio.run(run())

    assert "feature.txt" in diff
    assert commit.summary == "feature"
    assert store.list_commits(layout.workspace_id)[0].sha == commit.sha
    assert "commit" in [event.type for event in store.list_events(layout.workspace_id)]

