from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WorkflowState(str, Enum):
    INIT = "INIT"
    COLLECT_REQUIREMENTS = "COLLECT_REQUIREMENTS"
    PLAN = "PLAN"
    WAIT_FOR_USER_APPROVAL = "WAIT_FOR_USER_APPROVAL"
    CREATE_WORKTREES = "CREATE_WORKTREES"
    DISPATCH = "DISPATCH"
    MONITOR = "MONITOR"
    REVIEW = "REVIEW"
    MERGE_PLAN = "MERGE_PLAN"
    WAIT_FOR_FINAL_APPROVAL = "WAIT_FOR_FINAL_APPROVAL"
    DONE = "DONE"
    FAILED = "FAILED"


class Role(str, Enum):
    PLANNER = "planner"
    FRONTEND_CODER = "frontend-coder"
    BACKEND_CODER = "backend-coder"
    TESTER = "tester"
    REVIEWER = "reviewer"
    ORCHESTRATOR = "orchestrator"


class AgentStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"
    COMPLETED = "completed"
    REVIEWING = "reviewing"


class TaskStatus(str, Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    RUNNING = "running"
    BLOCKED = "blocked"
    REVIEW = "review"
    DONE = "done"
    FAILED = "failed"


class ReviewDecision(str, Enum):
    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"


class EventType(str, Enum):
    WORKSPACE_CREATED = "workspace_created"
    DAEMON_STARTED = "daemon_started"
    DAEMON_RESUMED = "daemon_resumed"
    STATE_TRANSITION = "state_transition"
    PLAN = "plan"
    ORCHESTRATOR_DECISION = "orchestrator_decision"
    USER_MESSAGE = "user_message"
    AGENT_MESSAGE = "agent_message"
    AGENT_CREATED = "agent_created"
    AGENT_STOPPED = "agent_stopped"
    AGENT_RESUMED = "agent_resumed"
    TASK_CREATED = "task_created"
    TASK_ASSIGNED = "task_assigned"
    READ_FILE = "read_file"
    WRITE_FILE = "write_file"
    TOOL_CALL = "tool_call"
    COMMAND = "command"
    DIFF = "diff"
    COMMIT = "commit"
    FAILED = "failed"
    SUMMARY = "summary"
    REVIEW = "review"
    WORKTREE_CREATED = "worktree_created"
    WORKTREE_REUSED = "worktree_reused"


class WorkspaceRecord(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    id: str
    repo_path: str
    state: WorkflowState = WorkflowState.INIT
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AgentRecord(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    id: int | None = None
    workspace_id: str
    name: str
    role: Role
    status: AgentStatus = AgentStatus.IDLE
    worktree_path: str | None = None
    branch: str | None = None
    current_goal: str | None = None
    current_action: str | None = None
    reasoning_summary: str | None = None
    next_action: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class TaskRecord(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    id: int | None = None
    workspace_id: str
    title: str
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    assigned_agent: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class EventRecord(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    id: int | None = None
    workspace_id: str
    sequence: int | None = None
    ts: datetime = Field(default_factory=utc_now)
    agent: str | None = None
    type: EventType | str
    message: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class StateTransitionRecord(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    id: int | None = None
    workspace_id: str
    from_state: WorkflowState
    to_state: WorkflowState
    reason: str
    ts: datetime = Field(default_factory=utc_now)


class CommitRecord(BaseModel):
    id: int | None = None
    workspace_id: str
    agent: str
    branch: str
    sha: str
    summary: str = ""
    ts: datetime = Field(default_factory=utc_now)


class ReviewRecord(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    id: int | None = None
    workspace_id: str
    reviewer: str
    implementer: str
    branch: str
    decision: ReviewDecision
    rationale: str
    ts: datetime = Field(default_factory=utc_now)
