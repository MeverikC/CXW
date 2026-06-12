from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from cxw.errors import WorktreeError
from cxw.events import EventBus
from cxw.models import AgentStatus, EventType, Role
from cxw.store import StateStore
from cxw.workspace import WorkspaceLayout, is_relative_to


class WorktreeManager:
    def __init__(self, layout: WorkspaceLayout, store: StateStore, bus: EventBus):
        self.layout = layout
        self.store = store
        self.bus = bus

    async def ensure_agent_worktree(self, agent_name: str) -> Path:
        agent = self.store.get_agent(self.layout.workspace_id, agent_name)
        if agent is None:
            raise WorktreeError(f"unknown agent: {agent_name}")
        existing = agent.worktree_path
        if existing:
            path = Path(existing)
            if path.exists():
                await self.bus.publish(
                    EventType.WORKTREE_REUSED,
                    agent=agent_name,
                    message=f"reusing worktree {path}",
                    payload={"path": str(path), "branch": agent.branch},
                )
                return path

        self._require_git()
        worktree_path = (self.layout.worktrees_dir / agent_name).resolve(strict=False)
        if not is_relative_to(worktree_path, self.layout.worktrees_dir):
            raise WorktreeError(f"unsafe worktree path resolved outside CXW worktree root: {worktree_path}")
        if worktree_path.exists() and not (worktree_path / ".git").exists():
            raise WorktreeError(f"worktree path exists but is not a git worktree: {worktree_path}")

        branch = f"cxw/{agent_name}"
        self._assert_worktree_not_owned(agent_name, worktree_path)
        self._add_worktree(worktree_path, branch)
        self.store.update_agent_worktree(self.layout.workspace_id, agent_name, worktree_path, branch)
        self.store.set_agent_status(self.layout.workspace_id, agent_name, AgentStatus.IDLE)
        await self.bus.publish(
            EventType.WORKTREE_CREATED,
            agent=agent_name,
            message=f"created worktree {worktree_path}",
            payload={"path": str(worktree_path), "branch": branch},
        )
        return worktree_path

    async def ensure_worker_worktrees(self) -> list[Path]:
        paths: list[Path] = []
        assigned_agents = {
            task.assigned_agent
            for task in self.store.list_tasks(self.layout.workspace_id)
            if task.assigned_agent
        }
        for agent in self.store.list_agents(self.layout.workspace_id):
            if agent.name not in assigned_agents or agent.role in {
                Role.PLANNER.value,
                Role.ORCHESTRATOR.value,
            }:
                continue
            paths.append(await self.ensure_agent_worktree(agent.name))
        return paths

    def _assert_worktree_not_owned(self, agent_name: str, path: Path) -> None:
        for agent in self.store.list_agents(self.layout.workspace_id):
            if agent.name != agent_name and agent.worktree_path == str(path):
                raise WorktreeError(f"worktree already owned by {agent.name}: {path}")

    def _require_git(self) -> None:
        if shutil.which("git") is None:
            raise WorktreeError("git executable not found")
        self._git("rev-parse", "--show-toplevel")

    def _branch_exists(self, branch: str) -> bool:
        result = subprocess.run(
            ["git", "-C", str(self.layout.repo_path), "branch", "--list", branch],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        return bool(result.stdout.strip())

    def _add_worktree(self, path: Path, branch: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and (path / ".git").exists():
            return
        if self._branch_exists(branch):
            args = ["worktree", "add", str(path), branch]
        else:
            args = ["worktree", "add", "-b", branch, str(path), "HEAD"]
        self._git(*args)

    def _git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.layout.repo_path), *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode != 0:
            raise WorktreeError(result.stderr.strip() or result.stdout.strip() or "git command failed")
        return result.stdout
