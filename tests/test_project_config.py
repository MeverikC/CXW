from __future__ import annotations

from cxw.project_config import TEMPLATE, inspect_project_config


def test_missing_project_config_creates_invalid_template(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    status = inspect_project_config(repo, create_template=True)

    assert status.exists is True
    assert status.valid is False
    assert status.created_template is True
    assert (repo / "CXW.toml").read_text(encoding="utf-8") == TEMPLATE


def test_project_config_rejects_unknown_assigned_agent(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "CXW.toml").write_text(
        """
[workspace]
name = "Demo"
goal = "Coordinate one implementation task."

[[roles]]
name = "planner-1"
role = "planner"
instructions = "Plan the work."

[[tasks]]
title = "Implement feature"
description = "Change the code."
assigned_agent = "missing-1"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    status = inspect_project_config(repo)

    assert status.valid is False
    assert "unknown agent" in status.errors[0]


def test_project_config_accepts_custom_agent_names_without_frontend_backend_defaults(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "CXW.toml").write_text(
        """
[workspace]
name = "Docs Tool"
goal = "Coordinate one documentation workflow."

[[roles]]
name = "planner-1"
role = "planner"
instructions = "Plan the documentation work."

[[roles]]
name = "engineer-1"
role = "backend-coder"
instructions = "Implement the scoped repository change."

[[tasks]]
title = "Draft usage guide"
description = "Create the usage guide."
assigned_agent = "engineer-1"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    status = inspect_project_config(repo)

    assert status.valid is True
    assert status.config is not None
    assert [role.name for role in status.config.roles] == ["planner-1", "engineer-1"]
    assert status.declared_runtime is None


def test_project_config_accepts_agents_alias_and_codex_runtime_overrides(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "CXW.toml").write_text(
        """
[workspace]
name = "Agent Runtime"
goal = "Coordinate a Codex MCP worker."

[main_agent]
name = "lead-1"
instructions = "Plan and coordinate all workers."

[defaults.codex]
runtime = "codex-mcp"
model = "gpt-5.5"
base_url = "http://127.0.0.1:15721/v1"
goal_mode = true
approval_delegate = "lead-1"
approval_policy = "on-request"
sandbox_mode = "workspace-write"
max_iterations = 20
max_runtime_minutes = 60

[[agents]]
name = "planner-1"
role = "planner"
instructions = "Plan the work."

[[agents]]
name = "engineer-1"
role = "backend-coder"
instructions = "Implement the scoped repository change."

[agents.codex]
model = "gpt-5-mini"
max_runtime_minutes = 30

[[tasks]]
title = "Implement feature"
description = "Change the code."
assigned_agent = "engineer-1"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    status = inspect_project_config(repo)

    assert status.valid is True
    assert status.config is not None
    assert status.config.main_agent.name == "lead-1"
    assert status.declared_runtime == "codex-mcp"
    assert status.to_snapshot()["declared_runtime"] == "codex-mcp"
    assert [role.name for role in status.config.roles] == ["planner-1", "engineer-1"]
    engineer_runtime = status.config.codex_config_for_agent("engineer-1")
    assert engineer_runtime.model == "gpt-5-mini"
    assert engineer_runtime.base_url == "http://127.0.0.1:15721/v1"
    assert engineer_runtime.approval_delegate == "lead-1"
    assert engineer_runtime.max_runtime_minutes == 30


def test_project_config_rejects_codex_todo_placeholders(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "CXW.toml").write_text(
        """
[workspace]
name = "Agent Runtime"
goal = "Coordinate a Codex MCP worker."

[defaults.codex]
model = "TODO: model"

[[agents]]
name = "planner-1"
role = "planner"
instructions = "Plan the work."

[[agents]]
name = "engineer-1"
role = "backend-coder"
instructions = "Implement the scoped repository change."

[[tasks]]
title = "Implement feature"
description = "Change the code."
assigned_agent = "engineer-1"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    status = inspect_project_config(repo)

    assert status.valid is False
    assert any("must replace TODO" in error for error in status.errors)
