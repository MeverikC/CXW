from __future__ import annotations

from dataclasses import dataclass
import json
import re
import shlex

from cxw.agents.runtime import runtime_from_environment
from cxw.codex_home import CodexAgentRuntimeConfig, CodexHomeManager
from cxw.errors import CodexRuntimeError
from cxw.events import EventBus
from cxw.models import (
    AgentRecord,
    AgentStatus,
    EventType,
    ReviewDecision,
    Role,
    StateTransitionRecord,
    TaskRecord,
    TaskStatus,
    WorkflowState,
    WorkspaceRecord,
)
from cxw.project_config import ProjectConfig, ProjectConfigStatus, inspect_project_config
from cxw.review import ReviewService
from cxw.store import StateStore
from cxw.summaries import SummaryService
from cxw.workspace import WorkspaceLayout
from cxw.worktrees import WorktreeManager


IMPLEMENTER_ROLES = {Role.FRONTEND_CODER.value, Role.BACKEND_CODER.value}


ALLOWED_TRANSITIONS: dict[WorkflowState, set[WorkflowState]] = {
    WorkflowState.INIT: {WorkflowState.COLLECT_REQUIREMENTS, WorkflowState.FAILED},
    WorkflowState.COLLECT_REQUIREMENTS: {WorkflowState.PLAN, WorkflowState.FAILED},
    WorkflowState.PLAN: {WorkflowState.WAIT_FOR_USER_APPROVAL, WorkflowState.FAILED},
    WorkflowState.WAIT_FOR_USER_APPROVAL: {WorkflowState.CREATE_WORKTREES, WorkflowState.FAILED},
    WorkflowState.CREATE_WORKTREES: {WorkflowState.DISPATCH, WorkflowState.FAILED},
    WorkflowState.DISPATCH: {WorkflowState.MONITOR, WorkflowState.FAILED},
    WorkflowState.MONITOR: {WorkflowState.REVIEW, WorkflowState.FAILED},
    WorkflowState.REVIEW: {WorkflowState.MERGE_PLAN, WorkflowState.FAILED},
    WorkflowState.MERGE_PLAN: {WorkflowState.WAIT_FOR_FINAL_APPROVAL, WorkflowState.FAILED},
    WorkflowState.WAIT_FOR_FINAL_APPROVAL: {WorkflowState.DONE, WorkflowState.FAILED},
    WorkflowState.DONE: set(),
    WorkflowState.FAILED: {WorkflowState.COLLECT_REQUIREMENTS},
}


@dataclass
class Orchestrator:
    layout: WorkspaceLayout
    store: StateStore
    bus: EventBus

    async def ensure_initialized(self) -> WorkspaceRecord:
        workspace = self.store.get_workspace(self.layout.workspace_id)
        if workspace is None:
            workspace = WorkspaceRecord(
                id=self.layout.workspace_id,
                repo_path=str(self.layout.repo_path),
                state=WorkflowState.INIT,
            )
            self.store.upsert_workspace(workspace)
            await self.bus.publish(
                EventType.WORKSPACE_CREATED,
                agent="orchestrator",
                message="workspace created",
                payload={"repo_path": str(self.layout.repo_path)},
            )
            await self.transition(
                WorkflowState.COLLECT_REQUIREMENTS,
                "workspace initialized and ready to collect requirements",
            )

        status = await self.ensure_project_config()
        self._ensure_main_agent(status.config if status.valid else None)
        await self._ensure_codex_homes(status.config if status.valid else None)
        if status.valid and status.config:
            self._ensure_configured_agents(status.config)
            if self.current_state() == WorkflowState.COLLECT_REQUIREMENTS and not self.store.list_tasks(
                self.layout.workspace_id
            ):
                await self.transition(WorkflowState.PLAN, f"project plan loaded from {status.path}")
                await self._create_configured_plan(status.config, status.path)
                await self.transition(WorkflowState.WAIT_FOR_USER_APPROVAL, "configured plan ready")
        return self.store.get_workspace(self.layout.workspace_id) or workspace

    async def ensure_project_config(self) -> ProjectConfigStatus:
        status = inspect_project_config(self.layout.repo_path, create_template=True)
        if status.created_template:
            await self.bus.publish(
                EventType.ORCHESTRATOR_DECISION,
                agent="orchestrator",
                message="project plan template created",
                payload=status.to_snapshot(),
            )
        return status

    def project_config_status(self) -> ProjectConfigStatus:
        return inspect_project_config(self.layout.repo_path, create_template=False)

    async def resume(self) -> None:
        await self.ensure_initialized()
        await self.bus.publish(
            EventType.DAEMON_RESUMED,
            agent="orchestrator",
            message="workspace state recovered from persistence",
            payload={"state": self.current_state().value},
        )
        await self._advance_review_workflow_if_ready()

    async def approve_plan(self) -> None:
        await self._run_plan()

    async def run_plan(self, runtime_name: str | None = None) -> str:
        await self.ensure_initialized()
        main_name = self._main_agent_name()
        display = "/run" + (f" --runtime {runtime_name}" if runtime_name else "")
        await self.bus.publish(
            EventType.USER_MESSAGE,
            agent=main_name,
            message=display,
            payload={"role": "user", "command": "run", "runtime": runtime_name},
        )
        reply = await self._run_plan(runtime_name=runtime_name)
        await self.bus.publish(
            EventType.AGENT_MESSAGE,
            agent=main_name,
            message=reply,
            payload={"role": "assistant", "command": "run", "runtime": runtime_name},
        )
        return reply

    async def _run_plan(self, runtime_name: str | None = None) -> str:
        await self.ensure_initialized()
        if self.current_state() == WorkflowState.COLLECT_REQUIREMENTS:
            status = inspect_project_config(self.layout.repo_path, create_template=True)
            if not status.valid or status.config is None:
                await self.bus.publish(
                    EventType.ORCHESTRATOR_DECISION,
                    agent="orchestrator",
                    message="project plan is not ready to run",
                    payload=status.to_snapshot(),
                )
                raise ValueError(
                    "CXW.toml must be completed before running a plan: "
                    + "; ".join(status.errors)
                )
            self._ensure_configured_agents(status.config)
            await self.transition(WorkflowState.PLAN, f"project plan loaded from {status.path}")
            await self._create_configured_plan(status.config, status.path)
            await self.transition(WorkflowState.WAIT_FOR_USER_APPROVAL, "configured plan ready")
        if self.current_state() != WorkflowState.WAIT_FOR_USER_APPROVAL:
            return (
                f"当前工作流状态是 `{self.current_state().value}`，`/run` 未重复派发任务。"
                "需要调整计划时使用 `/plan ...`。"
            )
        if self.current_state() == WorkflowState.WAIT_FOR_USER_APPROVAL:
            await self.transition(WorkflowState.CREATE_WORKTREES, "user requested plan execution")
            try:
                manager = WorktreeManager(self.layout, self.store, self.bus)
                await manager.ensure_worker_worktrees()
                await self.transition(WorkflowState.DISPATCH, "agent worktrees ready")
                await self._dispatch_pending_tasks(runtime_name=runtime_name)
                await self.transition(WorkflowState.MONITOR, "tasks dispatched")
                await self._advance_review_workflow_if_ready()
            except Exception as exc:
                await self.fail(f"worktree creation or dispatch failed: {exc}")
                raise
        return "执行已启动：CXW 已创建/复用 worker worktree，并按计划派发待执行任务。"

    async def final_approve(self) -> None:
        if self.current_state() == WorkflowState.WAIT_FOR_FINAL_APPROVAL:
            await self.transition(WorkflowState.DONE, "human final approval recorded")

    async def stop_agent(self, name: str) -> None:
        if self.store.get_agent(self.layout.workspace_id, name) is None:
            raise ValueError(f"unknown agent: {name}")
        self.store.set_agent_status(self.layout.workspace_id, name, AgentStatus.STOPPED)
        await self.bus.publish(
            EventType.AGENT_STOPPED,
            agent=name,
            message=f"{name} stopped",
            payload={"decision": "agent paused by user"},
        )

    async def queue_main_message(self, message: str) -> str:
        text = message.strip()
        if not text:
            raise ValueError("message must not be empty")
        await self.ensure_initialized()
        main_name = self._main_agent_name()
        status = self.project_config_status()
        queued = self.current_state() in {
            WorkflowState.CREATE_WORKTREES,
            WorkflowState.DISPATCH,
            WorkflowState.MONITOR,
            WorkflowState.REVIEW,
            WorkflowState.MERGE_PLAN,
        }
        self.store.update_agent_transparency(
            self.layout.workspace_id,
            main_name,
            current_goal="process user request",
            current_action="queued user message" if queued else "received user message",
            reasoning_summary="user input is persisted as an orchestrator-visible event",
            next_action="plan, schedule, or wait for active tasks to finish",
        )
        await self.bus.publish(
            EventType.USER_MESSAGE,
            agent=main_name,
            message=text,
            payload={"role": "user", "queued": queued},
        )
        reply = self._build_main_agent_reply(text, status)
        await self.bus.publish(
            EventType.AGENT_MESSAGE,
            agent=main_name,
            message=reply,
            payload={"role": "assistant", "queued": queued},
        )
        return reply

    async def handle_plan_command(self, command: str) -> str:
        await self.ensure_initialized()
        main_name = self._main_agent_name()
        text = command.strip()
        await self.bus.publish(
            EventType.USER_MESSAGE,
            agent=main_name,
            message=f"/plan {text}".rstrip(),
            payload={"role": "user", "command": "plan", "args": text},
        )
        reply, changed = self._execute_plan_command(text)
        if changed:
            await self.ensure_initialized()
            await self._sync_configured_plan_changes()
        await self.bus.publish(
            EventType.AGENT_MESSAGE,
            agent=main_name,
            message=reply,
            payload={"role": "assistant", "command": "plan", "args": text, "changed": changed},
        )
        return reply

    async def fail(self, reason: str) -> None:
        await self.transition(WorkflowState.FAILED, reason)
        await self.bus.publish(
            EventType.FAILED,
            agent="orchestrator",
            message=reason,
            payload={"failure_policy": ["retry", "reassign", "escalate", "ask_user"]},
        )

    async def transition(self, to_state: WorkflowState, reason: str) -> None:
        workspace = self.store.get_workspace(self.layout.workspace_id)
        if workspace is None:
            raise ValueError("workspace not initialized")
        from_state = WorkflowState(workspace.state)
        if from_state == to_state:
            return
        if to_state not in ALLOWED_TRANSITIONS[from_state]:
            raise ValueError(f"invalid transition {from_state.value} -> {to_state.value}")
        self.store.update_workspace_state(self.layout.workspace_id, to_state)
        transition = self.store.append_transition(
            StateTransitionRecord(
                workspace_id=self.layout.workspace_id,
                from_state=from_state,
                to_state=to_state,
                reason=reason,
            )
        )
        await self.bus.publish(
            EventType.STATE_TRANSITION,
            agent="orchestrator",
            message=f"{from_state.value} -> {to_state.value}",
            payload=transition.model_dump(mode="json"),
        )

    def current_state(self) -> WorkflowState:
        workspace = self.store.get_workspace(self.layout.workspace_id)
        return WorkflowState(workspace.state) if workspace else WorkflowState.INIT

    def _main_agent_name(self) -> str:
        status = self.project_config_status()
        if status.valid and status.config:
            return status.config.main_agent.name
        return "main-1"

    def _ensure_configured_agents(self, config: ProjectConfig) -> None:
        self._ensure_main_agent(config)
        for role_config in config.roles:
            role = Role(role_config.role)
            name = role_config.name
            existing = self.store.get_agent(self.layout.workspace_id, name)
            if existing is None:
                self.store.upsert_agent(
                    AgentRecord(
                        workspace_id=self.layout.workspace_id,
                        name=name,
                        role=role,
                        status=AgentStatus.IDLE,
                        current_goal="waiting for orchestrator assignment",
                        current_action="idle",
                        reasoning_summary=role_config.instructions,
                        next_action="wait for dispatch",
                    )
                )
            else:
                self.store.upsert_agent(
                    AgentRecord(
                        id=existing.id,
                        workspace_id=self.layout.workspace_id,
                        name=name,
                        role=role,
                        status=AgentStatus(existing.status),
                        worktree_path=existing.worktree_path,
                        branch=existing.branch,
                        current_goal=existing.current_goal,
                        current_action=existing.current_action,
                        reasoning_summary=role_config.instructions,
                        next_action=existing.next_action,
                        created_at=existing.created_at,
                    )
                )

    def _ensure_main_agent(self, config: ProjectConfig | None = None) -> None:
        name = config.main_agent.name if config else "main-1"
        instructions = (
            config.main_agent.instructions
            if config
            else "Plan, schedule, monitor, delegate approvals, and keep the CXW workflow moving."
        )
        existing = self.store.get_agent(self.layout.workspace_id, name)
        if existing is None:
            self.store.upsert_agent(
                AgentRecord(
                    workspace_id=self.layout.workspace_id,
                    name=name,
                    role=Role.ORCHESTRATOR,
                    status=AgentStatus.IDLE,
                    current_goal="waiting for user requirements",
                    current_action="idle",
                    reasoning_summary=instructions,
                    next_action="collect requirements and coordinate worker agents",
                )
            )
            return
        self.store.upsert_agent(
            AgentRecord(
                id=existing.id,
                workspace_id=self.layout.workspace_id,
                name=name,
                role=Role.ORCHESTRATOR,
                status=AgentStatus(existing.status),
                worktree_path=existing.worktree_path,
                branch=existing.branch,
                current_goal=existing.current_goal,
                current_action=existing.current_action,
                reasoning_summary=instructions,
                next_action=existing.next_action,
                created_at=existing.created_at,
            )
        )

    async def _ensure_codex_homes(self, config: ProjectConfig | None) -> None:
        manager = CodexHomeManager(self.layout.repo_path)
        expected_metadata_paths = self._expected_codex_metadata_paths(manager, config)
        already_prepared = all(path.exists() for path in expected_metadata_paths)
        homes = []
        try:
            if config is None:
                homes.append(
                    manager.prepare_main_home(CodexAgentRuntimeConfig(), require_auth=False)
                )
            else:
                homes.append(
                    manager.prepare_main_home(
                        config.codex_config_for_agent(config.main_agent.name),
                        name=config.main_agent.name,
                        require_auth=False,
                    )
                )
                for role in config.roles:
                    homes.append(
                        manager.prepare_agent_home(
                            role.name,
                            config.codex_config_for_agent(role.name),
                            require_auth=False,
                        )
                    )
        except CodexRuntimeError as exc:
            await self.bus.publish(
                EventType.FAILED,
                agent="orchestrator",
                message=f"Codex home preparation failed: {exc}",
                payload={"codex_home_root": str(manager.root)},
            )
            return

        if not already_prepared:
            await self.bus.publish(
                EventType.SUMMARY,
                agent="orchestrator",
                message="Codex agent homes prepared",
                payload={
                    "codex_home_root": str(manager.root),
                    "homes": [home.to_snapshot() for home in homes],
                },
            )

    def _expected_codex_metadata_paths(
        self, manager: CodexHomeManager, config: ProjectConfig | None
    ) -> list:
        if config is None:
            return [manager.root / "main-1" / "cxw-agent.json"]
        paths = [manager.root / config.main_agent.name / "cxw-agent.json"]
        paths.extend(manager.root / "agents" / role.name / "cxw-agent.json" for role in config.roles)
        return paths

    def _build_main_agent_reply(self, message: str, status: ProjectConfigStatus) -> str:
        if _is_greeting(message):
            return (
                "我是 CXW 的 main agent，负责把你的需求整理成计划、维护 agent/task "
                "分工、推动审批和调度。当前我可以正常接收对话；计划操作请使用 "
                "`/plan init`、`/plan auto`、`/plan add`、`/plan edit`，执行使用 `/run`。"
            )

        if not status.valid:
            return (
                "我收到你的消息了。当前项目计划还没准备好，`CXW.toml` 仍需要补全。"
                "如果你希望我生成草案，请使用 `/plan auto <项目目标、技术栈、验收要求>`。"
            )

        return (
            "我收到你的消息了。当前计划有效，可以输入 `/run` 开始执行；"
            "计划调整请使用 `/plan add` 或 `/plan edit`。"
        )

    def _execute_plan_command(self, command: str) -> tuple[str, bool]:
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            return f"plan 命令解析失败: {exc}\n{_plan_usage()}", False
        if not argv or argv[0] in {"help", "-h", "--help"}:
            return _plan_usage(), False

        subcommand = argv[0]
        args = argv[1:]
        status = self.project_config_status()
        if subcommand == "status":
            return _plan_status_reply(status), False
        if subcommand == "init":
            return self._plan_init(args, status)
        if subcommand == "auto":
            return self._plan_auto(args, status)
        if subcommand == "add":
            return self._plan_add(args)
        if subcommand == "edit":
            return self._plan_edit(args)
        return f"未知 plan 子命令: {subcommand}\n{_plan_usage()}", False

    def _plan_init(self, args: list[str], status: ProjectConfigStatus) -> tuple[str, bool]:
        goal = " ".join(args).strip()
        if not goal:
            return (
                f"计划文件位置: `{status.path}`。\n"
                "如果要生成草案，请使用 `/plan init <项目目标>` 或 `/plan auto <项目目标>`。",
                False,
            )
        return self._write_plan_draft_if_safe(goal, status, force=False)

    def _plan_auto(self, args: list[str], status: ProjectConfigStatus) -> tuple[str, bool]:
        force = "--force" in args
        goal = " ".join(arg for arg in args if arg != "--force").strip()
        if not goal:
            return "用法: `/plan auto <项目目标、技术栈、验收要求>`，可选 `--force`。", False
        return self._write_plan_draft_if_safe(goal, status, force=force)

    def _plan_add(self, args: list[str]) -> tuple[str, bool]:
        if not args:
            return (
                "用法: `/plan add agent <name> <role> <instructions...>` 或 "
                "`/plan add task <agent> <title> -- <description>`。",
                False,
            )
        target = args[0]
        if target == "agent":
            return self._plan_add_agent(args[1:])
        if target == "task":
            return self._plan_add_task(args[1:])
        return "用法: `/plan add agent ...` 或 `/plan add task ...`。", False

    def _plan_add_agent(self, args: list[str]) -> tuple[str, bool]:
        if len(args) < 2:
            return "用法: `/plan add agent <name> <role> <instructions...>`。", False
        name, role = args[0], args[1]
        if role not in {item.value for item in Role if item != Role.ORCHESTRATOR}:
            return f"未知 role: {role}。可用 role: planner, frontend-coder, backend-coder, tester, reviewer。", False
        instructions = " ".join(args[2:]).strip() or f"Work as {role} for the CXW plan."
        with self.project_config_status().path.open("a", encoding="utf-8") as file:
            file.write(
                "\n[[agents]]\n"
                f"name = {_toml_string(name)}\n"
                f"role = {_toml_string(role)}\n"
                f"instructions = {_toml_string(instructions)}\n"
            )
        return f"已添加 agent `{name}`，role `{role}`。运行 `/plan status` 检查配置。", True

    def _plan_add_task(self, args: list[str]) -> tuple[str, bool]:
        if len(args) < 2:
            return "用法: `/plan add task <agent> <title> -- <description>`。", False
        agent = args[0]
        rest = args[1:]
        if "--" in rest:
            split_at = rest.index("--")
            title = " ".join(rest[:split_at]).strip()
            description = " ".join(rest[split_at + 1 :]).strip()
        else:
            title = rest[0]
            description = " ".join(rest[1:]).strip()
        if not title:
            return "task title 不能为空。", False
        description = description or title
        with self.project_config_status().path.open("a", encoding="utf-8") as file:
            file.write(
                "\n[[tasks]]\n"
                f"title = {_toml_string(title)}\n"
                f"description = {_toml_multiline(description)}\n"
                f"assigned_agent = {_toml_string(agent)}\n"
            )
        return f"已添加 task `{title}`，assigned_agent `{agent}`。运行 `/plan status` 检查配置。", True

    def _plan_edit(self, args: list[str]) -> tuple[str, bool]:
        if not args:
            return (
                f"计划文件位置: `{self.project_config_status().path}`。\n"
                "可用: `/plan edit name <项目名>` 或 `/plan edit goal <目标>`。",
                False,
            )
        field = args[0]
        value = " ".join(args[1:]).strip()
        if field not in {"name", "goal"}:
            return "可编辑字段: `name`, `goal`。", False
        if not value:
            return f"用法: `/plan edit {field} <新值>`。", False
        path = self.project_config_status().path
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        updated = _replace_workspace_field(current, field, value)
        path.write_text(updated, encoding="utf-8")
        return f"已更新 workspace.{field}。运行 `/plan status` 检查配置。", True

    def _write_plan_draft_if_safe(
        self, goal: str, status: ProjectConfigStatus, *, force: bool
    ) -> tuple[str, bool]:
        path = status.path
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if status.valid and not force:
            return "`CXW.toml` 当前已经有效。若要重建草案，请使用 `/plan auto --force <目标>`。", False
        if current and "TODO" not in current and not force:
            return (
                "`CXW.toml` 不是纯模板，未自动覆盖。若确认覆盖，请使用 "
                "`/plan auto --force <目标>`。"
            ), False
        path.write_text(_draft_project_config(goal), encoding="utf-8")
        return (
            "我已生成 `CXW.toml` 草案。运行 `/plan status` 检查，确认后输入 `/run`。",
            True,
        )

    async def _create_configured_plan(self, config: ProjectConfig, config_path) -> None:
        if self.store.list_tasks(self.layout.workspace_id):
            return
        planner = next(role for role in config.roles if role.role == Role.PLANNER)
        for task in config.tasks:
            created = self.store.create_task(
                TaskRecord(
                    workspace_id=self.layout.workspace_id,
                    title=task.title,
                    description=task.description,
                    assigned_agent=task.assigned_agent,
                )
            )
            await self.bus.publish(
                EventType.TASK_CREATED,
                agent="orchestrator",
                message=created.title,
                payload=created.model_dump(mode="json"),
            )
        await self.bus.publish(
            EventType.PLAN,
            agent=planner.name,
            message="configured project plan loaded",
            payload={
                "config_path": str(config_path),
                "workspace_goal": config.workspace.goal,
                "task_count": len(config.tasks),
                "requires_user_approval": True,
            },
        )

    async def _sync_configured_plan_changes(self) -> None:
        status = self.project_config_status()
        if not status.valid or status.config is None:
            return
        config = status.config
        self._ensure_configured_agents(config)
        existing = {
            (task.title, task.assigned_agent)
            for task in self.store.list_tasks(self.layout.workspace_id)
        }
        created_count = 0
        for task in config.tasks:
            key = (task.title, task.assigned_agent)
            if key in existing:
                continue
            created = self.store.create_task(
                TaskRecord(
                    workspace_id=self.layout.workspace_id,
                    title=task.title,
                    description=task.description,
                    assigned_agent=task.assigned_agent,
                )
            )
            created_count += 1
            await self.bus.publish(
                EventType.TASK_CREATED,
                agent="orchestrator",
                message=created.title,
                payload=created.model_dump(mode="json"),
            )
        if created_count:
            await self.bus.publish(
                EventType.PLAN,
                agent=self._main_agent_name(),
                message="configured project plan synchronized",
                payload={
                    "config_path": str(status.path),
                    "created_tasks": created_count,
                    "task_count": len(config.tasks),
                },
            )

    async def _dispatch_pending_tasks(self, runtime_name: str | None = None) -> None:
        runtime = runtime_from_environment(
            self.store,
            self.bus,
            self.layout,
            runtime=runtime_name or self._configured_runtime_name(),
        )
        agents = {agent.name: agent for agent in self.store.list_agents(self.layout.workspace_id)}
        for task in self.store.list_tasks(self.layout.workspace_id):
            if task.id is None or TaskStatus(task.status) == TaskStatus.DONE:
                continue
            if not task.assigned_agent:
                continue
            agent = agents.get(task.assigned_agent)
            if agent is None:
                await self.fail(f"task assigned to missing agent: {task.assigned_agent}")
                return
            self.store.update_task(task.id, status=TaskStatus.RUNNING)
            try:
                await runtime.dispatch(agent, task)
            except Exception:
                self.store.update_task(task.id, status=TaskStatus.FAILED)
                raise
            refreshed_agent = self.store.get_agent(self.layout.workspace_id, agent.name)
            if refreshed_agent and AgentStatus(refreshed_agent.status) == AgentStatus.COMPLETED:
                self.store.update_task(task.id, status=TaskStatus.DONE)
                await self.bus.publish(
                    EventType.SUMMARY,
                    agent="orchestrator",
                    message=f"task completed: {task.title}",
                    payload={"task_id": task.id, "assigned_agent": task.assigned_agent},
                )
            else:
                self.store.update_task(task.id, status=TaskStatus.ASSIGNED)

    async def _advance_review_workflow_if_ready(self) -> None:
        state = self.current_state()
        if state == WorkflowState.MONITOR:
            tasks = self.store.list_tasks(self.layout.workspace_id)
            if not tasks:
                return
            statuses = {TaskStatus(task.status) for task in tasks}
            if TaskStatus.FAILED in statuses or TaskStatus.BLOCKED in statuses:
                await self.fail("one or more tasks failed or blocked before review")
                return
            if any(status != TaskStatus.DONE for status in statuses):
                return
            await self.transition(WorkflowState.REVIEW, "all dispatched tasks completed")
            state = WorkflowState.REVIEW

        if state == WorkflowState.REVIEW:
            await self._ensure_review_records()
            await self.transition(
                WorkflowState.MERGE_PLAN,
                "review gate completed and branch decisions persisted",
            )
            state = WorkflowState.MERGE_PLAN

        if state == WorkflowState.MERGE_PLAN:
            await SummaryService(self.store, self.bus, self.layout.workspace_id).generate()
            await self.transition(
                WorkflowState.WAIT_FOR_FINAL_APPROVAL,
                "merge plan generated; waiting for human final approval",
            )

    async def _ensure_review_records(self) -> None:
        existing_reviewed_branches = {
            review.branch for review in self.store.list_reviews(self.layout.workspace_id)
        }
        commits_by_branch = {
            commit.branch: commit for commit in self.store.list_commits(self.layout.workspace_id)
        }
        reviewer = self._reviewer_name()
        service = ReviewService(self.store, self.bus, self.layout.workspace_id)
        for agent in self.store.list_agents(self.layout.workspace_id):
            if agent.role not in IMPLEMENTER_ROLES or not agent.branch:
                continue
            if agent.branch in existing_reviewed_branches:
                continue
            commit = commits_by_branch.get(agent.branch)
            if commit is None:
                rationale = (
                    "No implementation commit has been recorded for this branch. "
                    "Human review is required before merge."
                )
            else:
                rationale = (
                    f"Review gate captured commit {commit.sha[:12]}. "
                    "A human reviewer must inspect the diff and verification summary before merge."
                )
            await service.record_review(
                reviewer=reviewer,
                implementer=agent.name,
                branch=agent.branch,
                decision=ReviewDecision.REQUEST_CHANGES,
                rationale=rationale,
            )

    def _reviewer_name(self) -> str:
        for agent in self.store.list_agents(self.layout.workspace_id):
            if agent.role == Role.REVIEWER.value:
                return agent.name
        return self._main_agent_name()

    def _configured_runtime_name(self) -> str | None:
        status = self.project_config_status()
        if status.valid and status.declared_runtime:
            return status.declared_runtime
        return None


def _is_greeting(message: str) -> bool:
    lowered = message.lower().strip()
    return lowered in {"hi", "hello", "hey", "你好", "你好,", "你好，你是谁", "你是谁"} or any(
        token in lowered for token in ("你是谁", "能干什么", "可以做什么")
    )


def _plan_usage() -> str:
    return (
        "Plan commands:\n"
        "- `/plan status` 查看 CXW.toml 状态。\n"
        "- `/plan init <目标>` 在模板/空计划上生成初始草案。\n"
        "- `/plan auto <目标>` 自动生成草案；已有非模板计划需加 `--force`。\n"
        "- `/plan add agent <name> <role> <instructions...>` 追加 agent。\n"
        "- `/plan add task <agent> <title> -- <description>` 追加 task。\n"
        "- `/plan edit name <项目名>` 或 `/plan edit goal <目标>` 编辑 workspace 字段。\n"
        "- 计划确认后使用 `/run` 创建 worktree 并派发 agent。"
    )


def _plan_status_reply(status: ProjectConfigStatus) -> str:
    if status.valid and status.config:
        return (
            f"`CXW.toml` 有效: `{status.path}`\n"
            f"Workspace: {status.config.workspace.name}\n"
            f"Agents: {len(status.config.roles)} | Tasks: {len(status.config.tasks)}"
        )
    errors = "; ".join(status.errors[:4]) if status.errors else "unknown error"
    return f"`CXW.toml` 尚未有效: `{status.path}`\n{errors}"


def _draft_project_config(goal: str) -> str:
    goal = goal.strip() or "Coordinate a scoped engineering project."
    wants_stack = _mentions_any(
        goal,
        ("react", "tailwind", "fastapi", "前端", "后端", "frontend", "backend", "api"),
    )
    project_name = "Lottery Stack" if _mentions_any(goal, ("抽奖", "lottery")) else "Generated Project"
    if wants_stack:
        agents = """
[[agents]]
name = "planner-1"
role = "planner"
instructions = "Turn the workspace goal into an execution plan and keep state transitions explicit."

[[agents]]
name = "frontend-1"
role = "frontend-coder"
instructions = "Implement the frontend experience in an isolated worktree."

[[agents]]
name = "backend-1"
role = "backend-coder"
instructions = "Implement the backend API and persistence behavior in an isolated worktree."

[[agents]]
name = "tester-1"
role = "tester"
instructions = "Run focused verification and report risks before final approval."
"""
        tasks = f"""
[[tasks]]
title = "Implement frontend experience"
description = {_toml_multiline("Build the frontend for this goal:\n" + goal)}
assigned_agent = "frontend-1"

[[tasks]]
title = "Implement backend API"
description = {_toml_multiline("Build the backend/API support for this goal:\n" + goal)}
assigned_agent = "backend-1"

[[tasks]]
title = "Verify integrated workflow"
description = {_toml_multiline("Run focused frontend, backend, and integration checks for this goal:\n" + goal)}
assigned_agent = "tester-1"
"""
    else:
        agents = """
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
"""
        tasks = f"""
[[tasks]]
title = "Implement scoped project"
description = {_toml_multiline("Implement this goal:\n" + goal)}
assigned_agent = "engineer-1"

[[tasks]]
title = "Verify scoped project"
description = {_toml_multiline("Run focused checks for this goal:\n" + goal)}
assigned_agent = "tester-1"
"""

    return f"""# CXW project plan generated by main-1.

[workspace]
name = {_toml_string(project_name)}
goal = {_toml_multiline(goal)}

[main_agent]
name = "main-1"
instructions = "Plan, schedule, monitor, delegate approvals, and keep the CXW workflow moving."

[defaults.codex]
runtime = "codex-mcp"
goal_mode = true
approval_delegate = "main-1"
approval_policy = "on-request"
sandbox_mode = "workspace-write"
max_iterations = 20
max_runtime_minutes = 60
{agents}
{tasks}
"""


def _mentions_any(text: str, tokens: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(token.lower() in lowered for token in tokens)


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toml_multiline(value: str) -> str:
    escaped = value.replace('"""', '\\"\\"\\"')
    return f'"""{escaped}"""'


def _replace_workspace_field(content: str, field: str, value: str) -> str:
    replacement = f"{field} = {_toml_multiline(value) if field == 'goal' else _toml_string(value)}"
    pattern = re.compile(
        rf"(^\[workspace\]\s*(?:(?!^\[).)*?^{field}\s*=\s*)(?:\"\"\".*?\"\"\"|\".*?\")",
        re.MULTILINE | re.DOTALL,
    )
    if pattern.search(content):
        return pattern.sub(lambda match: match.group(1) + replacement.split(" = ", 1)[1], content, count=1)
    workspace_match = re.search(r"^\[workspace\]\s*$", content, re.MULTILINE)
    if workspace_match:
        insert_at = workspace_match.end()
        return content[:insert_at] + "\n" + replacement + content[insert_at:]
    return "[workspace]\n" + replacement + "\n\n" + content
