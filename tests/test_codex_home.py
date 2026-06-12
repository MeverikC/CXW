from __future__ import annotations

import json
import tomllib

import pytest

from cxw.codex_home import CodexAgentRuntimeConfig, CodexHomeManager
from cxw.errors import CodexRuntimeError


def _source_codex_home(tmp_path):
    source = tmp_path / "source-codex"
    source.mkdir()
    (source / "auth.json").write_text('{"token":"secret-token"}\n', encoding="utf-8")
    (source / "config.toml").write_text(
        """
model_provider = "custom"
model = "gpt-5"
disable_response_storage = true

[model_providers.custom]
name = "custom"
wire_api = "responses"
requires_openai_auth = true
base_url = "http://old.local/v1"
""".lstrip(),
        encoding="utf-8",
    )
    return source


def test_prepare_worker_home_copies_auth_and_merges_codex_config(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    source = _source_codex_home(tmp_path)
    manager = CodexHomeManager(repo, source_home=source)

    home = manager.prepare_agent_home(
        "frontend-1",
        CodexAgentRuntimeConfig(
            model="gpt-5.5",
            base_url="http://127.0.0.1:15721/v1",
            approval_delegate="main-1",
            max_iterations=42,
            max_runtime_minutes=90,
        ),
    )

    assert home.path == repo / ".codex" / "cxw" / "agents" / "frontend-1"
    assert home.auth_copied is True
    assert home.auth_path.read_text(encoding="utf-8") == '{"token":"secret-token"}\n'
    assert ".codex/" in (repo / ".gitignore").read_text(encoding="utf-8").splitlines()

    config = tomllib.loads(home.config_path.read_text(encoding="utf-8"))
    assert config["model"] == "gpt-5.5"
    assert config["model_provider"] == "custom"
    assert config["disable_response_storage"] is True
    assert config["approval_policy"] == "on-request"
    assert config["sandbox_mode"] == "workspace-write"
    assert config["model_providers"]["custom"]["base_url"] == "http://127.0.0.1:15721/v1"

    metadata = json.loads(home.metadata_path.read_text(encoding="utf-8"))
    assert metadata["agent_name"] == "frontend-1"
    assert metadata["kind"] == "worker"
    assert metadata["goal_mode"] is True
    assert metadata["max_iterations"] == 42
    assert "secret-token" not in home.metadata_path.read_text(encoding="utf-8")


def test_prepare_main_home_uses_main_path(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    manager = CodexHomeManager(repo, source_home=_source_codex_home(tmp_path))

    home = manager.prepare_main_home(CodexAgentRuntimeConfig(model="gpt-5.5"))

    assert home.path == repo / ".codex" / "cxw" / "main-1"
    assert home.env() == {"CODEX_HOME": str(home.path)}


def test_prepare_home_requires_auth_by_default(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    source = tmp_path / "empty-codex"
    source.mkdir()
    manager = CodexHomeManager(repo, source_home=source)

    with pytest.raises(CodexRuntimeError, match="Codex auth not found"):
        manager.prepare_agent_home("backend-1")


def test_prepare_home_can_skip_auth_for_dry_setup(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    source = tmp_path / "empty-codex"
    source.mkdir()
    manager = CodexHomeManager(repo, source_home=source)

    home = manager.prepare_agent_home("backend-1", require_auth=False)

    assert home.auth_copied is False
    assert not home.auth_path.exists()
