from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from cxw.errors import WorkspaceError
from cxw.events import EventBus
from cxw.models import CommitRecord, EventType
from cxw.store import StateStore
from cxw.workspace import WorkspaceLayout, is_relative_to


def _tail(value: str, limit: int = 4000) -> str:
    if len(value) <= limit:
        return value
    return value[-limit:]


@dataclass
class AgentEventCapture:
    """Reusable event capture helpers for agent runtimes and tooling adapters."""

    layout: WorkspaceLayout
    store: StateStore
    bus: EventBus

    async def read_text(self, agent_name: str, path: str | Path, *, encoding: str = "utf-8") -> str:
        target = self._resolve_agent_path(agent_name, path)
        content = target.read_text(encoding=encoding)
        await self.bus.publish(
            EventType.READ_FILE,
            agent=agent_name,
            message=f"read {target.relative_to(self._agent_root(agent_name))}",
            payload={"path": str(target), "bytes": len(content.encode(encoding))},
        )
        return content

    async def write_text(
        self,
        agent_name: str,
        path: str | Path,
        content: str,
        *,
        encoding: str = "utf-8",
    ) -> Path:
        target = self._resolve_agent_path(agent_name, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding=encoding)
        await self.bus.publish(
            EventType.WRITE_FILE,
            agent=agent_name,
            message=f"wrote {target.relative_to(self._agent_root(agent_name))}",
            payload={"path": str(target), "bytes": len(content.encode(encoding))},
        )
        return target

    async def run_command(
        self,
        agent_name: str,
        args: Sequence[str],
        *,
        cwd: str | Path | None = None,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if not args:
            raise WorkspaceError("command args cannot be empty")
        root = self._agent_root(agent_name)
        working_dir = self._resolve_agent_path(agent_name, cwd or root)
        result = await asyncio.to_thread(
            subprocess.run,
            list(args),
            cwd=str(working_dir),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        await self.bus.publish(
            EventType.COMMAND,
            agent=agent_name,
            message=f"command exited {result.returncode}: {' '.join(args)}",
            payload={
                "args": list(args),
                "cwd": str(working_dir),
                "returncode": result.returncode,
                "stdout_tail": _tail(result.stdout),
                "stderr_tail": _tail(result.stderr),
            },
        )
        return result

    async def capture_git_diff(self, agent_name: str) -> str:
        root = self._agent_root(agent_name)
        status = await self.run_command(agent_name, ["git", "status", "--short"], cwd=root)
        unstaged = await self.run_command(agent_name, ["git", "diff", "--stat"], cwd=root)
        staged = await self.run_command(agent_name, ["git", "diff", "--cached", "--stat"], cwd=root)
        diff_stat = "\n".join(
            part
            for part in (
                "status:\n" + status.stdout.strip() if status.stdout.strip() else "",
                "unstaged:\n" + unstaged.stdout.strip() if unstaged.stdout.strip() else "",
                "staged:\n" + staged.stdout.strip() if staged.stdout.strip() else "",
            )
            if part
        )
        await self.bus.publish(
            EventType.DIFF,
            agent=agent_name,
            message="captured git diff stat",
            payload={"worktree": str(root), "diff_stat": diff_stat},
        )
        return diff_stat

    async def record_commit(
        self,
        agent_name: str,
        *,
        sha: str | None = None,
        summary: str = "",
    ) -> CommitRecord:
        agent = self.store.get_agent(self.layout.workspace_id, agent_name)
        if agent is None:
            raise WorkspaceError(f"unknown agent: {agent_name}")
        root = self._agent_root(agent_name)
        commit_sha = sha or self._git_output(root, "rev-parse", "HEAD")
        branch = agent.branch or self._git_output(root, "rev-parse", "--abbrev-ref", "HEAD")
        record = self.store.append_commit(
            CommitRecord(
                workspace_id=self.layout.workspace_id,
                agent=agent_name,
                branch=branch,
                sha=commit_sha,
                summary=summary,
            )
        )
        await self.bus.publish(
            EventType.COMMIT,
            agent=agent_name,
            message=f"commit recorded {commit_sha[:12]}",
            payload=record.model_dump(mode="json"),
        )
        return record

    def _agent_root(self, agent_name: str) -> Path:
        agent = self.store.get_agent(self.layout.workspace_id, agent_name)
        if agent is None:
            raise WorkspaceError(f"unknown agent: {agent_name}")
        root = Path(agent.worktree_path) if agent.worktree_path else self.layout.repo_path
        return root.resolve(strict=False)

    def _resolve_agent_path(self, agent_name: str, path: str | Path) -> Path:
        root = self._agent_root(agent_name)
        candidate = Path(path)
        resolved = candidate.resolve(strict=False) if candidate.is_absolute() else (root / candidate).resolve(strict=False)
        if not is_relative_to(resolved, root):
            raise WorkspaceError(f"refusing to access path outside agent root: {resolved}")
        return resolved

    @staticmethod
    def _git_output(root: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode != 0:
            raise WorkspaceError(result.stderr.strip() or result.stdout.strip() or "git failed")
        return result.stdout.strip()
