from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from cxw.codex_home import DEFAULT_MAIN_AGENT, CodexAgentRuntimeConfig
from cxw.models import Role

CONFIG_FILENAME = "CXW.toml"


TEMPLATE = """# CXW project plan
# Edit this file, replace every TODO, then run:
#   cxw <repo> run
#
# Built-in role kinds:
#   planner, frontend-coder, backend-coder, tester, reviewer

[workspace]
name = "TODO: project name"
goal = "TODO: describe the engineering outcome CXW should coordinate."

[main_agent]
name = "main-1"
instructions = "Plan, schedule, monitor, delegate approvals, and keep the CXW workflow moving."

[defaults.codex]
runtime = "codex-mcp"
model = "TODO: codex model name, for example gpt-5.5"
base_url = "TODO: OpenAI-compatible base URL, for example http://127.0.0.1:15721/v1"
goal_mode = true
approval_delegate = "main-1"
approval_policy = "on-request"
sandbox_mode = "workspace-write"
max_iterations = 20
max_runtime_minutes = 60

[[agents]]
name = "planner-1"
role = "planner"
instructions = "Turn the workspace goal into an execution plan and keep state transitions explicit."

[[agents]]
name = "engineer-1"
role = "backend-coder"
instructions = "Implement the scoped engineering task in an isolated worktree."

[[agents]]
name = "tester-1"
role = "tester"
instructions = "Run focused verification and report risks before final approval."

[[tasks]]
title = "TODO: implementation task title"
description = "TODO: describe the exact work engineer-1 should complete."
assigned_agent = "engineer-1"

[[tasks]]
title = "TODO: verification task title"
description = "TODO: describe the checks tester-1 should run."
assigned_agent = "tester-1"
"""


def config_path_for_repo(repo_path: str | Path) -> Path:
    return Path(repo_path).expanduser().resolve(strict=False) / CONFIG_FILENAME


def _is_placeholder(value: str) -> bool:
    return "TODO" in value


class WorkspaceConfig(BaseModel):
    name: str
    goal: str

    @field_validator("name", "goal")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        if _is_placeholder(text):
            raise ValueError("must replace TODO placeholder text")
        return text


class RoleConfig(BaseModel):
    name: str
    role: Role
    instructions: str = ""
    codex: CodexAgentRuntimeConfig | None = None

    @field_validator("name", "instructions")
    @classmethod
    def _text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        if _is_placeholder(text):
            raise ValueError("must replace TODO placeholder text")
        return text

    @field_validator("role")
    @classmethod
    def _role_must_be_assignable(cls, value: Role) -> Role:
        if value == Role.ORCHESTRATOR:
            raise ValueError("orchestrator is not a configurable worker role")
        return value


class TaskConfig(BaseModel):
    title: str
    description: str
    assigned_agent: str

    @field_validator("title", "description", "assigned_agent")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        if _is_placeholder(text):
            raise ValueError("must replace TODO placeholder text")
        return text


class MainAgentConfig(BaseModel):
    name: str = DEFAULT_MAIN_AGENT
    instructions: str = (
        "Plan, schedule, monitor, delegate approvals, and keep the CXW workflow moving."
    )
    codex: CodexAgentRuntimeConfig | None = None

    @field_validator("name", "instructions")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        if _is_placeholder(text):
            raise ValueError("must replace TODO placeholder text")
        return text


class DefaultsConfig(BaseModel):
    codex: CodexAgentRuntimeConfig = Field(default_factory=CodexAgentRuntimeConfig)


class ProjectConfig(BaseModel):
    workspace: WorkspaceConfig
    main_agent: MainAgentConfig = Field(default_factory=MainAgentConfig)
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    roles: list[RoleConfig] = Field(default_factory=list)
    agents: list[RoleConfig] = Field(default_factory=list)
    tasks: list[TaskConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_project_contract(self) -> "ProjectConfig":
        if self.agents:
            self.roles = [*self.roles, *self.agents]
            self.agents = []
        if not self.roles:
            raise ValueError("at least one worker agent is required")
        if not self.tasks:
            raise ValueError("at least one task is required")

        role_names = [role.name for role in self.roles]
        duplicate_roles = sorted({name for name in role_names if role_names.count(name) > 1})
        if duplicate_roles:
            raise ValueError(f"worker agent names must be unique: {', '.join(duplicate_roles)}")
        if self.main_agent.name in role_names:
            raise ValueError(
                f"main agent name must be distinct from worker agents: {self.main_agent.name}"
            )

        roles_by_name = {role.name: role for role in self.roles}
        planner_roles = [role for role in self.roles if role.role == Role.PLANNER]
        if not planner_roles:
            raise ValueError("one planner role is required")

        for task in self.tasks:
            role = roles_by_name.get(task.assigned_agent)
            if role is None:
                raise ValueError(
                    f"task '{task.title}' is assigned to unknown agent '{task.assigned_agent}'"
                )
            if role.role in {Role.PLANNER, Role.ORCHESTRATOR}:
                raise ValueError(
                    f"task '{task.title}' cannot be assigned to {role.role.value} agent "
                    f"'{task.assigned_agent}'"
                )
        return self

    def codex_config_for_agent(self, agent_name: str) -> CodexAgentRuntimeConfig:
        base = self.defaults.codex
        override: CodexAgentRuntimeConfig | None = None
        if agent_name == self.main_agent.name:
            override = self.main_agent.codex
        else:
            for role in self.roles:
                if role.name == agent_name:
                    override = role.codex
                    break

        data = base.model_dump()
        if override is not None:
            for field_name in override.model_fields_set:
                data[field_name] = getattr(override, field_name)
        if data.get("approval_delegate") == DEFAULT_MAIN_AGENT and self.main_agent.name != DEFAULT_MAIN_AGENT:
            data["approval_delegate"] = self.main_agent.name
        return CodexAgentRuntimeConfig.model_validate(data)


@dataclass(frozen=True)
class ProjectConfigStatus:
    path: Path
    exists: bool
    valid: bool
    created_template: bool = False
    errors: list[str] = field(default_factory=list)
    config: ProjectConfig | None = None
    declared_runtime: str | None = None

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "exists": self.exists,
            "valid": self.valid,
            "created_template": self.created_template,
            "errors": list(self.errors),
            "declared_runtime": self.declared_runtime,
            "workspace": self.config.workspace.model_dump(mode="json") if self.config else None,
            "main_agent": self.config.main_agent.model_dump(mode="json") if self.config else None,
            "defaults": self.config.defaults.model_dump(mode="json") if self.config else None,
            "roles": [role.model_dump(mode="json") for role in self.config.roles]
            if self.config
            else [],
            "tasks": [task.model_dump(mode="json") for task in self.config.tasks]
            if self.config
            else [],
        }


def inspect_project_config(repo_path: str | Path, *, create_template: bool = False) -> ProjectConfigStatus:
    path = config_path_for_repo(repo_path)
    if not path.exists():
        if create_template:
            path.write_text(TEMPLATE, encoding="utf-8")
            return ProjectConfigStatus(
                path=path,
                exists=True,
                valid=False,
                created_template=True,
                errors=[f"created template at {path}; replace TODO values before running a plan"],
            )
        return ProjectConfigStatus(
            path=path,
            exists=False,
            valid=False,
            errors=[f"missing required project plan: {path}"],
        )

    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        return ProjectConfigStatus(path=path, exists=True, valid=False, errors=[str(exc)])
    except OSError as exc:
        return ProjectConfigStatus(path=path, exists=True, valid=False, errors=[str(exc)])

    try:
        config = ProjectConfig.model_validate(raw)
    except ValidationError as exc:
        errors = [
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        ]
        return ProjectConfigStatus(path=path, exists=True, valid=False, errors=errors)

    return ProjectConfigStatus(
        path=path,
        exists=True,
        valid=True,
        config=config,
        declared_runtime=_declared_runtime(raw),
    )


def _declared_runtime(raw: dict[str, Any]) -> str | None:
    runtime = _runtime_from_mapping(raw.get("defaults"), "codex")
    if runtime:
        return runtime
    runtime = _runtime_from_mapping(raw.get("main_agent"), "codex")
    if runtime:
        return runtime
    for key in ("agents", "roles"):
        value = raw.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            runtime = _runtime_from_mapping(item, "codex")
            if runtime:
                return runtime
    return None


def _runtime_from_mapping(value: Any, nested_key: str) -> str | None:
    if not isinstance(value, dict):
        return None
    nested = value.get(nested_key)
    if not isinstance(nested, dict):
        return None
    runtime = nested.get("runtime")
    if not isinstance(runtime, str):
        return None
    return runtime.strip().lower() or None
