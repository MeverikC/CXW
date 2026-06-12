from __future__ import annotations

import asyncio
import shutil
import subprocess

import pytest

from cxw.events import EventBus
from cxw.models import AgentStatus, CommitRecord, TaskStatus, WorkflowState
from cxw.orchestrator import Orchestrator
from cxw.project_config import inspect_project_config
from cxw.store import StateStore
from cxw.workspace import WorkspaceLayout


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )


def _init_git_repo(repo):
    _git(repo, "init")
    _git(repo, "config", "user.email", "cxw@example.test")
    _git(repo, "config", "user.name", "CXW Test")
    (repo / "README.md").write_text("# repo\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")


def _write_project_config(repo):
    (repo / "CXW.toml").write_text(
        """
[workspace]
name = "Tiny Library"
goal = "Coordinate a focused Python library improvement."

[[roles]]
name = "planner-1"
role = "planner"
instructions = "Plan the work and keep approval boundaries explicit."

[[roles]]
name = "engineer-1"
role = "backend-coder"
instructions = "Implement the Python library change."

[[roles]]
name = "tester-1"
role = "tester"
instructions = "Verify the Python library change."

[[tasks]]
title = "Implement board sorting"
description = "Add deterministic task ordering to the Python library."
assigned_agent = "engineer-1"

[[tasks]]
title = "Verify board sorting"
description = "Run focused tests for deterministic task ordering."
assigned_agent = "tester-1"
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _write_codex_home(path):
    path.mkdir()
    (path / "auth.json").write_text('{"token":"test-token"}\n', encoding="utf-8")
    (path / "config.toml").write_text('model = "gpt-5.5"\n', encoding="utf-8")


def test_orchestrator_creates_template_when_project_config_is_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("CXW_HOME", str(tmp_path / "cxw-home"))
    source_codex = tmp_path / "source-codex"
    _write_codex_home(source_codex)
    monkeypatch.setenv("CODEX_HOME", str(source_codex))
    repo = tmp_path / "repo"
    repo.mkdir()
    layout = WorkspaceLayout.from_repo(repo)
    store = StateStore(layout)
    bus = EventBus(store, layout.workspace_id)
    orchestrator = Orchestrator(layout, store, bus)

    asyncio.run(orchestrator.ensure_initialized())

    workspace = store.get_workspace(layout.workspace_id)
    assert workspace is not None
    assert workspace.state == WorkflowState.COLLECT_REQUIREMENTS
    assert (repo / "CXW.toml").exists()
    assert (repo / ".codex" / "cxw" / "main-1" / "config.toml").exists()
    assert (repo / ".codex" / "cxw" / "main-1" / "auth.json").read_text(
        encoding="utf-8"
    ) == '{"token":"test-token"}\n'
    assert [agent.name for agent in store.list_agents(layout.workspace_id)] == ["main-1"]
    assert store.list_tasks(layout.workspace_id) == []
    assert store.list_transitions(layout.workspace_id)[0].to_state == WorkflowState.COLLECT_REQUIREMENTS


def test_orchestrator_loads_configured_roles_and_plan(tmp_path, monkeypatch):
    monkeypatch.setenv("CXW_HOME", str(tmp_path / "cxw-home"))
    source_codex = tmp_path / "source-codex"
    _write_codex_home(source_codex)
    monkeypatch.setenv("CODEX_HOME", str(source_codex))
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_project_config(repo)
    layout = WorkspaceLayout.from_repo(repo)
    store = StateStore(layout)
    bus = EventBus(store, layout.workspace_id)
    orchestrator = Orchestrator(layout, store, bus)

    asyncio.run(orchestrator.ensure_initialized())

    workspace = store.get_workspace(layout.workspace_id)
    assert workspace is not None
    assert workspace.state == WorkflowState.WAIT_FOR_USER_APPROVAL
    assert {agent.name for agent in store.list_agents(layout.workspace_id)} == {
        "main-1",
        "planner-1",
        "engineer-1",
        "tester-1",
    }
    assert [task.assigned_agent for task in store.list_tasks(layout.workspace_id)] == [
        "engineer-1",
        "tester-1",
    ]
    assert (repo / ".codex" / "cxw" / "main-1" / "config.toml").exists()
    assert (repo / ".codex" / "cxw" / "agents" / "engineer-1" / "config.toml").exists()
    assert (repo / ".codex" / "cxw" / "agents" / "tester-1" / "config.toml").exists()


def test_resume_publishes_recovery_event(tmp_path, monkeypatch):
    monkeypatch.setenv("CXW_HOME", str(tmp_path / "cxw-home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_project_config(repo)
    layout = WorkspaceLayout.from_repo(repo)
    store = StateStore(layout)
    bus = EventBus(store, layout.workspace_id)
    orchestrator = Orchestrator(layout, store, bus)

    async def run():
        await orchestrator.ensure_initialized()
        await orchestrator.resume()

    asyncio.run(run())

    event_types = [event.type for event in store.list_events(layout.workspace_id)]
    assert "daemon_resumed" in event_types


def test_plan_auto_generates_project_plan_from_template(tmp_path, monkeypatch):
    monkeypatch.setenv("CXW_HOME", str(tmp_path / "cxw-home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    layout = WorkspaceLayout.from_repo(repo)
    store = StateStore(layout)
    bus = EventBus(store, layout.workspace_id)
    orchestrator = Orchestrator(layout, store, bus)

    async def run():
        await orchestrator.ensure_initialized()
        return await orchestrator.handle_plan_command(
            "auto 做一个前后端集成的抽奖项目, 前端 React TailwindCSS, 后端 FastAPI"
        )

    reply = asyncio.run(run())
    status = inspect_project_config(repo)
    events = store.list_events(layout.workspace_id)

    assert "已生成 `CXW.toml` 草案" in reply
    assert status.valid is True
    assert status.config is not None
    assert [role.name for role in status.config.roles] == [
        "planner-1",
        "frontend-1",
        "backend-1",
        "tester-1",
    ]
    assert [task.assigned_agent for task in status.config.tasks] == [
        "frontend-1",
        "backend-1",
        "tester-1",
    ]
    assert any(event.type == "user_message" for event in events)
    assert any(event.type == "agent_message" for event in events)


def test_main_agent_chat_does_not_generate_plan_from_text_matching(tmp_path, monkeypatch):
    monkeypatch.setenv("CXW_HOME", str(tmp_path / "cxw-home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    layout = WorkspaceLayout.from_repo(repo)
    store = StateStore(layout)
    bus = EventBus(store, layout.workspace_id)
    orchestrator = Orchestrator(layout, store, bus)

    async def run():
        await orchestrator.ensure_initialized()
        return await orchestrator.queue_main_message(
            "生成计划: 做一个前后端集成的抽奖项目, 前端 React TailwindCSS, 后端 FastAPI"
        )

    reply = asyncio.run(run())
    status = inspect_project_config(repo)

    assert "/plan auto" in reply
    assert status.valid is False


def test_plan_add_and_edit_commands_update_project_config(tmp_path, monkeypatch):
    monkeypatch.setenv("CXW_HOME", str(tmp_path / "cxw-home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    layout = WorkspaceLayout.from_repo(repo)
    store = StateStore(layout)
    bus = EventBus(store, layout.workspace_id)
    orchestrator = Orchestrator(layout, store, bus)

    async def run():
        await orchestrator.ensure_initialized()
        await orchestrator.handle_plan_command("auto simple library")
        await orchestrator.handle_plan_command("edit name Updated Library")
        await orchestrator.handle_plan_command(
            "add agent reviewer-1 reviewer Review implementation branches"
        )
        return await orchestrator.handle_plan_command(
            'add task reviewer-1 "Review implementation" -- "Review generated branches."'
        )

    reply = asyncio.run(run())
    status = inspect_project_config(repo)

    assert "已添加 task" in reply
    assert status.valid is True
    assert status.config is not None
    assert status.config.workspace.name == "Updated Library"
    assert any(role.name == "reviewer-1" for role in status.config.roles)
    assert any(task.assigned_agent == "reviewer-1" for task in status.config.tasks)
    assert any(task.assigned_agent == "reviewer-1" for task in store.list_tasks(layout.workspace_id))


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_run_plan_creates_worktrees_and_dispatches_tasks(tmp_path, monkeypatch):
    monkeypatch.setenv("CXW_HOME", str(tmp_path / "cxw-home"))
    monkeypatch.delenv("CXW_AGENT_RUNTIME", raising=False)
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    _write_project_config(repo)
    layout = WorkspaceLayout.from_repo(repo)
    store = StateStore(layout)
    bus = EventBus(store, layout.workspace_id)
    orchestrator = Orchestrator(layout, store, bus)

    async def run():
        await orchestrator.ensure_initialized()
        return await orchestrator.run_plan(runtime_name="local-deterministic")

    reply = asyncio.run(run())

    workspace = store.get_workspace(layout.workspace_id)
    assert workspace is not None
    assert workspace.state == WorkflowState.MONITOR
    assert "执行已启动" in reply
    engineer = store.get_agent(layout.workspace_id, "engineer-1")
    tester = store.get_agent(layout.workspace_id, "tester-1")
    assert engineer is not None and engineer.worktree_path
    assert tester is not None and tester.worktree_path
    assert (layout.worktrees_dir / "engineer-1").exists()
    assert (layout.worktrees_dir / "tester-1").exists()
    events = store.list_events(layout.workspace_id)
    assert any(event.type == "worktree_created" and event.agent == "engineer-1" for event in events)
    assert any(event.type == "task_assigned" and event.agent == "engineer-1" for event in events)
    assert any(
        event.type == "tool_call"
        and event.payload.get("runtime") == "local-deterministic"
        for event in events
    )
    assert {TaskStatus(task.status) for task in store.list_tasks(layout.workspace_id)} == {
        TaskStatus.ASSIGNED
    }


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_resume_advances_completed_tasks_through_review_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("CXW_HOME", str(tmp_path / "cxw-home"))
    monkeypatch.delenv("CXW_AGENT_RUNTIME", raising=False)
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    _write_project_config(repo)
    layout = WorkspaceLayout.from_repo(repo)
    store = StateStore(layout)
    bus = EventBus(store, layout.workspace_id)
    orchestrator = Orchestrator(layout, store, bus)

    async def run():
        await orchestrator.ensure_initialized()
        await orchestrator.run_plan(runtime_name="local-deterministic")
        for task in store.list_tasks(layout.workspace_id):
            assert task.id is not None
            store.update_task(task.id, status=TaskStatus.DONE)
        engineer = store.get_agent(layout.workspace_id, "engineer-1")
        assert engineer is not None and engineer.branch
        store.set_agent_status(layout.workspace_id, "engineer-1", AgentStatus.COMPLETED)
        store.append_commit(
            CommitRecord(
                workspace_id=layout.workspace_id,
                agent="engineer-1",
                branch=engineer.branch,
                sha="abcdef1234567890",
                summary="implementation checkpoint",
            )
        )
        await orchestrator.resume()

    asyncio.run(run())

    workspace = store.get_workspace(layout.workspace_id)
    assert workspace is not None
    assert workspace.state == WorkflowState.WAIT_FOR_FINAL_APPROVAL
    reviews = store.list_reviews(layout.workspace_id)
    assert len(reviews) == 1
    assert reviews[0].implementer == "engineer-1"
    assert reviews[0].decision == "request_changes"
    transitions = [transition.to_state for transition in store.list_transitions(layout.workspace_id)]
    assert WorkflowState.REVIEW in transitions
    assert WorkflowState.MERGE_PLAN in transitions
    assert WorkflowState.WAIT_FOR_FINAL_APPROVAL in transitions
