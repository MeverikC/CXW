from __future__ import annotations

import json
import os
import shutil
import tomllib
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from cxw.errors import CodexRuntimeError
from cxw.workspace import canonical_repo_path, is_relative_to


CODEX_AGENT_ROOT = ".codex/cxw"
DEFAULT_MAIN_AGENT = "main-1"


class CodexAgentRuntimeConfig(BaseModel):
    """Non-secret runtime settings used to prepare an isolated Codex home."""

    model_config = ConfigDict(extra="forbid")

    runtime: str = "codex-mcp"
    model: str | None = None
    base_url: str | None = None
    model_provider: str = "custom"
    goal_mode: bool = True
    approval_delegate: str = DEFAULT_MAIN_AGENT
    approval_policy: str = "on-request"
    sandbox_mode: str = "workspace-write"
    max_iterations: int = Field(default=20, ge=1)
    max_runtime_minutes: int = Field(default=60, ge=1)

    @field_validator(
        "runtime",
        "model",
        "base_url",
        "model_provider",
        "approval_delegate",
        "approval_policy",
        "sandbox_mode",
        mode="before",
    )
    @classmethod
    def _clean_optional_text(cls, value: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        text = value.strip()
        if "TODO" in text:
            raise ValueError("must replace TODO placeholder text")
        return text or None


@dataclass(frozen=True)
class CodexAgentHome:
    agent_name: str
    path: Path
    auth_path: Path
    config_path: Path
    metadata_path: Path
    auth_copied: bool

    def env(self) -> dict[str, str]:
        return {"CODEX_HOME": str(self.path)}

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "path": str(self.path),
            "auth_path": str(self.auth_path),
            "config_path": str(self.config_path),
            "metadata_path": str(self.metadata_path),
            "auth_copied": self.auth_copied,
        }


class CodexHomeManager:
    """Prepare per-agent CODEX_HOME directories inside the target repository."""

    def __init__(self, repo_path: str | os.PathLike[str], source_home: Path | None = None):
        self.repo_path = canonical_repo_path(repo_path)
        self.root = self.repo_path / CODEX_AGENT_ROOT
        self.source_home = source_home or _current_codex_home()

    def prepare_main_home(
        self,
        config: CodexAgentRuntimeConfig | None = None,
        *,
        name: str = DEFAULT_MAIN_AGENT,
        require_auth: bool = True,
    ) -> CodexAgentHome:
        return self.prepare_agent_home(name, config, main=True, require_auth=require_auth)

    def prepare_agent_home(
        self,
        agent_name: str,
        config: CodexAgentRuntimeConfig | None = None,
        *,
        main: bool = False,
        require_auth: bool = True,
    ) -> CodexAgentHome:
        agent = _clean_agent_name(agent_name)
        config = config or CodexAgentRuntimeConfig()
        home = self._home_path(agent, main=main)
        if not is_relative_to(home, self.root):
            raise CodexRuntimeError(f"unsafe Codex home resolved outside repository .codex root: {home}")

        home.mkdir(parents=True, exist_ok=True)
        self.ensure_gitignore()
        auth_copied = self._copy_auth(home, require_auth=require_auth)
        self._write_config(home, config)
        self._write_metadata(home, agent, config, main=main, auth_copied=auth_copied)
        return CodexAgentHome(
            agent_name=agent,
            path=home,
            auth_path=home / "auth.json",
            config_path=home / "config.toml",
            metadata_path=home / "cxw-agent.json",
            auth_copied=auth_copied,
        )

    def ensure_gitignore(self) -> None:
        path = self.repo_path / ".gitignore"
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        lines = existing.splitlines()
        if any(line.strip() == ".codex/" for line in lines):
            return
        prefix = "" if not existing or existing.endswith("\n") else "\n"
        path.write_text(existing + prefix + ".codex/\n", encoding="utf-8")

    def _home_path(self, agent_name: str, *, main: bool) -> Path:
        if main:
            return (self.root / agent_name).resolve(strict=False)
        return (self.root / "agents" / agent_name).resolve(strict=False)

    def _copy_auth(self, home: Path, *, require_auth: bool) -> bool:
        source = self.source_home / "auth.json"
        target = home / "auth.json"
        if not source.exists():
            if require_auth:
                raise CodexRuntimeError(
                    f"Codex auth not found at {source}; run Codex login before starting MCP agents"
                )
            return False
        shutil.copy2(source, target)
        try:
            target.chmod(0o600)
        except OSError:
            pass
        return True

    def _write_config(self, home: Path, config: CodexAgentRuntimeConfig) -> None:
        merged = _load_toml(self.source_home / "config.toml")
        merged = _merge_codex_config(merged, config)
        (home / "config.toml").write_text(_dumps_toml(merged), encoding="utf-8")

    def _write_metadata(
        self,
        home: Path,
        agent_name: str,
        config: CodexAgentRuntimeConfig,
        *,
        main: bool,
        auth_copied: bool,
    ) -> None:
        metadata = {
            "agent_name": agent_name,
            "kind": "main" if main else "worker",
            "runtime": config.runtime,
            "model": config.model,
            "base_url": config.base_url,
            "model_provider": config.model_provider,
            "goal_mode": config.goal_mode,
            "approval_delegate": config.approval_delegate,
            "approval_policy": config.approval_policy,
            "sandbox_mode": config.sandbox_mode,
            "max_iterations": config.max_iterations,
            "max_runtime_minutes": config.max_runtime_minutes,
            "auth_copied": auth_copied,
        }
        (home / "cxw-agent.json").write_text(
            json.dumps(metadata, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _current_codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    if configured:
        return Path(configured).expanduser().resolve(strict=False)
    return Path.home() / ".codex"


def _clean_agent_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise CodexRuntimeError("agent name must not be empty")
    if "/" in name or "\\" in name or name in {".", ".."}:
        raise CodexRuntimeError(f"invalid agent name for Codex home: {value!r}")
    return name


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise CodexRuntimeError(f"invalid Codex config.toml at {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        return {}
    return loaded


def _merge_codex_config(
    source: dict[str, Any], config: CodexAgentRuntimeConfig
) -> dict[str, Any]:
    merged = deepcopy(source)
    if config.model:
        merged["model"] = config.model
    if config.approval_policy:
        merged["approval_policy"] = config.approval_policy
    if config.sandbox_mode:
        merged["sandbox_mode"] = config.sandbox_mode

    provider = config.model_provider or str(merged.get("model_provider") or "custom")
    if config.base_url:
        merged["model_provider"] = provider
        providers = merged.get("model_providers")
        if not isinstance(providers, dict):
            providers = {}
        provider_config = providers.get(provider)
        if not isinstance(provider_config, dict):
            provider_config = {}
        provider_config.setdefault("name", provider)
        provider_config.setdefault("wire_api", "responses")
        provider_config.setdefault("requires_openai_auth", True)
        provider_config["base_url"] = config.base_url
        providers[provider] = provider_config
        merged["model_providers"] = providers
    elif config.model_provider:
        merged["model_provider"] = provider
    return merged


def _dumps_toml(data: dict[str, Any]) -> str:
    lines: list[str] = []
    _write_table(lines, (), data)
    return "\n".join(lines).rstrip() + "\n"


def _write_table(lines: list[str], prefix: tuple[str, ...], data: dict[str, Any]) -> None:
    scalars: list[tuple[str, Any]] = []
    tables: list[tuple[str, dict[str, Any]]] = []
    for key in sorted(data):
        value = data[key]
        if isinstance(value, dict):
            tables.append((key, value))
        else:
            scalars.append((key, value))

    for key, value in scalars:
        lines.append(f"{key} = {_format_toml_value(value)}")
    for key, value in tables:
        if lines and lines[-1] != "":
            lines.append("")
        section = ".".join((*prefix, key))
        lines.append(f"[{section}]")
        _write_table(lines, (*prefix, key), value)


def _format_toml_value(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_format_toml_value(item) for item in value) + "]"
    if value is None:
        return '""'
    raise CodexRuntimeError(f"unsupported Codex config value for TOML serialization: {value!r}")
