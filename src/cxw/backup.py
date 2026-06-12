from __future__ import annotations

import json
import sqlite3
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from cxw.errors import WorkspaceError
from cxw.serialization import dumps_json
from cxw.workspace import WorkspaceLayout, cxw_home

BACKUP_FORMAT_VERSION = 1


@dataclass(frozen=True)
class BackupManifest:
    format_version: int
    created_at: str
    source_workspace_id: str
    source_repo_path: str
    source_workspace_root: str


@dataclass(frozen=True)
class BackupResult:
    archive_path: Path
    manifest: BackupManifest
    file_count: int


@dataclass(frozen=True)
class RestoreResult:
    archive_path: Path
    target_workspace_id: str
    target_repo_path: str
    target_workspace_root: Path
    restored_file_count: int


def default_backup_path(layout: WorkspaceLayout) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return cxw_home() / "backups" / f"{layout.workspace_id}-{timestamp}.cxw.zip"


def create_workspace_backup(
    repo_path: str | Path, archive_path: str | Path | None = None
) -> BackupResult:
    layout = WorkspaceLayout.from_repo(repo_path)
    if not layout.root.exists():
        raise WorkspaceError(f"workspace does not exist: {layout.root}")
    archive = Path(archive_path).expanduser().resolve(strict=False) if archive_path else default_backup_path(layout)
    archive.parent.mkdir(parents=True, exist_ok=True)

    manifest = BackupManifest(
        format_version=BACKUP_FORMAT_VERSION,
        created_at=datetime.now(timezone.utc).isoformat(),
        source_workspace_id=layout.workspace_id,
        source_repo_path=str(layout.repo_path),
        source_workspace_root=str(layout.root),
    )

    file_count = 0
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", dumps_json(asdict(manifest)))
        for file_path in _backup_files(layout.root):
            relative = file_path.relative_to(layout.root)
            zf.write(file_path, f"workspace/{relative.as_posix()}")
            file_count += 1

    return BackupResult(archive_path=archive, manifest=manifest, file_count=file_count)


def restore_workspace_backup(archive_path: str | Path, repo_path: str | Path) -> RestoreResult:
    archive = Path(archive_path).expanduser().resolve(strict=True)
    layout = WorkspaceLayout.from_repo(repo_path)
    if layout.root.exists() and any(layout.root.iterdir()):
        raise WorkspaceError(f"target workspace already contains files: {layout.root}")
    layout.ensure()

    restored = 0
    with zipfile.ZipFile(archive, "r") as zf:
        manifest = _read_manifest(zf)
        for info in zf.infolist():
            if info.filename == "manifest.json" or info.is_dir():
                continue
            relative = _safe_workspace_member(info.filename)
            if relative is None:
                continue
            target = (layout.root / relative).resolve(strict=False)
            layout.require_internal_path(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info, "r") as src, target.open("wb") as dst:
                dst.write(src.read())
            restored += 1

    _rewrite_sqlite_workspace_identity(layout, manifest)
    _rewrite_ndjson_workspace_identity(layout.events_path, layout.workspace_id)
    _write_restore_metadata(layout, archive, manifest)

    return RestoreResult(
        archive_path=archive,
        target_workspace_id=layout.workspace_id,
        target_repo_path=str(layout.repo_path),
        target_workspace_root=layout.root,
        restored_file_count=restored,
    )


def _backup_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not relative.parts:
            continue
        if relative.parts[0] == "run":
            continue
        if path.is_symlink() or not path.is_file():
            continue
        yield path


def _read_manifest(zf: zipfile.ZipFile) -> BackupManifest:
    try:
        raw = json.loads(zf.read("manifest.json").decode("utf-8"))
    except KeyError as exc:
        raise WorkspaceError("backup archive is missing manifest.json") from exc
    if int(raw.get("format_version", 0)) != BACKUP_FORMAT_VERSION:
        raise WorkspaceError(f"unsupported backup format: {raw.get('format_version')}")
    return BackupManifest(
        format_version=int(raw["format_version"]),
        created_at=str(raw["created_at"]),
        source_workspace_id=str(raw["source_workspace_id"]),
        source_repo_path=str(raw["source_repo_path"]),
        source_workspace_root=str(raw["source_workspace_root"]),
    )


def _safe_workspace_member(name: str) -> Path | None:
    path = Path(name)
    if path.is_absolute() or path.drive:
        raise WorkspaceError(f"unsafe absolute archive member: {name}")
    parts = path.parts
    if not parts or parts[0] != "workspace":
        return None
    relative = Path(*parts[1:]) if len(parts) > 1 else Path()
    if not relative.parts:
        return None
    if any(part == ".." for part in relative.parts):
        raise WorkspaceError(f"unsafe archive member path: {name}")
    if relative.parts[0] == "run":
        return None
    return relative


def _rewrite_sqlite_workspace_identity(layout: WorkspaceLayout, manifest: BackupManifest) -> None:
    if not layout.db_path.exists():
        return
    tables = ["agents", "tasks", "events", "state_transitions", "commits", "reviews"]
    with sqlite3.connect(layout.db_path) as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        for table in tables:
            conn.execute(
                f"UPDATE {table} SET workspace_id=? WHERE workspace_id=?",
                (layout.workspace_id, manifest.source_workspace_id),
            )
        conn.execute(
            "UPDATE workspaces SET id=?, repo_path=?, updated_at=? WHERE id=?",
            (
                layout.workspace_id,
                str(layout.repo_path),
                datetime.now(timezone.utc).isoformat(),
                manifest.source_workspace_id,
            ),
        )
        conn.execute("PRAGMA foreign_keys=ON")


def _rewrite_ndjson_workspace_identity(events_path: Path, workspace_id: str) -> None:
    if not events_path.exists():
        return
    rewritten: list[str] = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            rewritten.append(line)
            continue
        if isinstance(event, dict):
            event["workspace_id"] = workspace_id
            rewritten.append(dumps_json(event))
        else:
            rewritten.append(line)
    events_path.write_text("\n".join(rewritten) + ("\n" if rewritten else ""), encoding="utf-8")


def _write_restore_metadata(
    layout: WorkspaceLayout, archive: Path, manifest: BackupManifest
) -> None:
    metadata = {
        "restored_at": datetime.now(timezone.utc).isoformat(),
        "archive_path": str(archive),
        "source": asdict(manifest),
        "target": {
            "workspace_id": layout.workspace_id,
            "repo_path": str(layout.repo_path),
            "workspace_root": str(layout.root),
        },
    }
    (layout.root / "restore.json").write_text(dumps_json(metadata), encoding="utf-8")

