from __future__ import annotations

from dataclasses import dataclass
from importlib import resources

from cxw.models import Role


@dataclass(frozen=True)
class RolePrompt:
    role: Role
    name: str
    prompt: str


ROLE_PROMPT_FILES: dict[Role, str] = {
    Role.PLANNER: "planner.md",
    Role.FRONTEND_CODER: "frontend-coder.md",
    Role.BACKEND_CODER: "backend-coder.md",
    Role.TESTER: "tester.md",
    Role.REVIEWER: "reviewer.md",
}


DEFAULT_AGENT_NAMES: dict[Role, str] = {
    Role.PLANNER: "planner-1",
    Role.FRONTEND_CODER: "frontend-1",
    Role.BACKEND_CODER: "backend-1",
    Role.TESTER: "tester-1",
    Role.REVIEWER: "reviewer-1",
}


def load_role_prompt(role: Role) -> RolePrompt:
    file_name = ROLE_PROMPT_FILES[role]
    prompt = resources.files("cxw.prompts").joinpath(file_name).read_text(encoding="utf-8")
    return RolePrompt(role=role, name=role.value, prompt=prompt)


def built_in_role_prompts() -> dict[Role, RolePrompt]:
    return {role: load_role_prompt(role) for role in ROLE_PROMPT_FILES}


def default_agent_name(role: Role) -> str:
    return DEFAULT_AGENT_NAMES[role]

