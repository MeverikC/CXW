from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from cxw.errors import WorkspaceError


def canonical_repo_path(repo_path: str | os.PathLike[str]) -> Path:
    path = Path(repo_path).expanduser()
    try:
        return path.resolve(strict=False)
    except OSError as exc:
        raise WorkspaceError(f"cannot resolve repository path {repo_path!s}: {exc}") from exc


def workspace_id_for_repo(repo_path: str | os.PathLike[str]) -> str:
    canonical = str(canonical_repo_path(repo_path))
    base_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    # Include .git creation time to invalidate cache when repo is recreated
    git_dir = Path(canonical) / ".git"
    if git_dir.exists():
        try:
            git_ctime = str(int(git_dir.stat().st_ctime))
            return hashlib.sha256(f"{base_hash}:{git_ctime}".encode("utf-8")).hexdigest()
        except OSError:
            pass

    return base_hash


def cxw_home() -> Path:
    configured = os.environ.get("CXW_HOME")
    return Path(configured).expanduser().resolve(strict=False) if configured else Path.home() / ".cxw"


def is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except ValueError:
        return False


@dataclass(frozen=True)
class WorkspaceLayout:
    repo_path: Path
    workspace_id: str
    root: Path
    run_dir: Path
    logs_dir: Path
    worktrees_dir: Path
    db_path: Path
    events_path: Path
    endpoint_path: Path

    @classmethod
    def from_repo(cls, repo_path: str | os.PathLike[str]) -> "WorkspaceLayout":
        repo = canonical_repo_path(repo_path)
        workspace_id = workspace_id_for_repo(repo)
        root = cxw_home() / "workspaces" / workspace_id
        return cls(
            repo_path=repo,
            workspace_id=workspace_id,
            root=root,
            run_dir=root / "run",
            logs_dir=root / "logs",
            worktrees_dir=root / "worktrees",
            db_path=root / "state.sqlite3",
            events_path=root / "events.ndjson",
            endpoint_path=root / "run" / "endpoint.json",
        )

    def ensure(self) -> None:
        for path in (self.root, self.run_dir, self.logs_dir, self.worktrees_dir):
            path.mkdir(parents=True, exist_ok=True)

    def require_internal_path(self, path: Path) -> Path:
        resolved = path.resolve(strict=False)
        if not is_relative_to(resolved, self.root):
            raise WorkspaceError(f"refusing to operate outside workspace data root: {resolved}")
        return resolved

