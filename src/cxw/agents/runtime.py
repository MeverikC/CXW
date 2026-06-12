from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from cxw.agents.roles import load_role_prompt
from cxw.codex_home import CodexAgentRuntimeConfig, CodexHomeManager
from cxw.codex_mcp import McpStdioClient, codex_mcp_command_from_environment
from cxw.events import EventBus
from cxw.models import AgentRecord, AgentStatus, EventType, Role, TaskRecord, TaskStatus
from cxw.project_config import inspect_project_config
from cxw.store import StateStore
from cxw.workspace import WorkspaceLayout


class AgentRuntime(Protocol):
    async def dispatch(self, agent: AgentRecord, task: TaskRecord) -> None:
        """Dispatch a task to an agent implementation."""


@dataclass
class LocalDeterministicRuntime:
    """Deterministic runtime used until external Agents SDK/Codex MCP wiring is configured."""

    store: StateStore
    bus: EventBus

    async def dispatch(self, agent: AgentRecord, task: TaskRecord) -> None:
        self.store.update_agent_transparency(
            agent.workspace_id,
            agent.name,
            current_goal=task.title,
            current_action="awaiting external agent runtime",
            reasoning_summary="task assignment persisted; implementation runner not configured",
            next_action="configure OpenAI Agents SDK and Codex MCP adapter",
        )
        await self.bus.publish(
            EventType.TASK_ASSIGNED,
            agent=agent.name,
            message=f"assigned task: {task.title}",
            payload={"task_id": task.id, "status": TaskStatus.ASSIGNED.value},
        )
        await self.bus.publish(
            EventType.TOOL_CALL,
            agent=agent.name,
            message="agent runtime adapter boundary reached",
            payload={"runtime": "local-deterministic", "external_execution": False},
        )


@dataclass
class OpenAIAgentsRuntime:
    """Optional OpenAI Agents SDK adapter selected with CXW_AGENT_RUNTIME=openai-agents."""

    store: StateStore
    bus: EventBus
    model: str | None = None

    async def dispatch(self, agent: AgentRecord, task: TaskRecord) -> None:
        try:
            from agents import Agent, Runner
        except ImportError as exc:
            raise RuntimeError(
                "OpenAI Agents SDK is not installed. Install with `python -m pip install -e .[agents]`."
            ) from exc

        role_prompt = load_role_prompt(Role(agent.role))
        sdk_kwargs = {"name": agent.name, "instructions": role_prompt.prompt}
        if self.model:
            sdk_kwargs["model"] = self.model
        sdk_agent = Agent(**sdk_kwargs)

        self.store.update_agent_transparency(
            agent.workspace_id,
            agent.name,
            current_goal=task.title,
            current_action="running OpenAI Agents SDK task",
            reasoning_summary="task dispatched through configured external runtime",
            next_action="persist result summary and await orchestrator review",
        )
        await self.bus.publish(
            EventType.TOOL_CALL,
            agent=agent.name,
            message="OpenAI Agents SDK run started",
            payload={"runtime": "openai-agents", "task_id": task.id},
        )
        result = await Runner.run(sdk_agent, task.description or task.title)
        final_output = getattr(result, "final_output", str(result))
        await self.bus.publish(
            EventType.SUMMARY,
            agent=agent.name,
            message="OpenAI Agents SDK run completed",
            payload={"task_id": task.id, "summary": str(final_output)},
        )


@dataclass
class CodexMcpRuntime:
    """Codex MCP adapter spike: initialize a Codex MCP server and list tools."""

    store: StateStore
    bus: EventBus
    layout: WorkspaceLayout

    async def dispatch(self, agent: AgentRecord, task: TaskRecord) -> None:
        self.store.set_agent_status(agent.workspace_id, agent.name, AgentStatus.RUNNING)
        self.store.update_agent_transparency(
            agent.workspace_id,
            agent.name,
            current_goal=task.title,
            current_action="preparing isolated Codex MCP home",
            reasoning_summary="task will be handed to a Codex MCP runtime adapter",
            next_action="start Codex MCP server and inspect available tools",
        )

        try:
            runtime_config = self._runtime_config_for(agent.name)
            home = CodexHomeManager(self.layout.repo_path).prepare_agent_home(
                agent.name,
                runtime_config,
                main=Role(agent.role) == Role.ORCHESTRATOR,
                require_auth=True,
            )
            await self.bus.publish(
                EventType.TOOL_CALL,
                agent=agent.name,
                message="Codex MCP server probe starting",
                payload={
                    "runtime": "codex-mcp",
                    "task_id": task.id,
                    "codex_home": home.to_snapshot(),
                    "model": runtime_config.model,
                    "base_url": runtime_config.base_url,
                    "goal_mode": runtime_config.goal_mode,
                    "approval_delegate": runtime_config.approval_delegate,
                    "max_iterations": runtime_config.max_iterations,
                    "max_runtime_minutes": runtime_config.max_runtime_minutes,
                },
            )

            cwd = Path(agent.worktree_path) if agent.worktree_path else self.layout.repo_path
            async with McpStdioClient(
                codex_mcp_command_from_environment(),
                cwd=cwd,
                env=home.env(),
            ) as client:
                initialize_result = await client.initialize()
                tools = await client.list_tools()
                tool_names = {str(tool.get("name")) for tool in tools if isinstance(tool, dict)}
                if "codex" not in tool_names:
                    raise RuntimeError("Codex MCP server does not expose required 'codex' tool")
                codex_result = await client.call_tool(
                    "codex",
                    self._codex_tool_arguments(agent, task, runtime_config, cwd),
                )

            self.store.update_agent_transparency(
                agent.workspace_id,
                agent.name,
                current_goal=task.title,
                current_action="Codex MCP task completed",
                reasoning_summary="Codex MCP returned a task result for audit and review",
                next_action="await orchestrator review and merge planning",
            )
            self.store.set_agent_status(agent.workspace_id, agent.name, AgentStatus.COMPLETED)
            thread_id, content = _extract_codex_tool_output(codex_result)
            await self.bus.publish(
                EventType.SUMMARY,
                agent=agent.name,
                message="Codex MCP task completed",
                payload={
                    "runtime": "codex-mcp",
                    "task_id": task.id,
                    "server": initialize_result,
                    "tools": tools,
                    "tool_count": len(tools),
                    "thread_id": thread_id,
                    "content": content,
                },
            )
        except Exception as exc:
            self.store.set_agent_status(agent.workspace_id, agent.name, AgentStatus.FAILED)
            await self.bus.publish(
                EventType.FAILED,
                agent=agent.name,
                message=f"Codex MCP runtime failed: {exc}",
                payload={"runtime": "codex-mcp", "task_id": task.id},
            )
            raise

    def _runtime_config_for(self, agent_name: str) -> CodexAgentRuntimeConfig:
        status = inspect_project_config(self.layout.repo_path, create_template=False)
        if status.valid and status.config:
            return status.config.codex_config_for_agent(agent_name)
        return CodexAgentRuntimeConfig()

    def _codex_tool_arguments(
        self,
        agent: AgentRecord,
        task: TaskRecord,
        runtime_config: CodexAgentRuntimeConfig,
        cwd: Path,
    ) -> dict[str, Any]:
        role_prompt = load_role_prompt(Role(agent.role)).prompt
        prompt = (
            f"CXW agent: {agent.name}\n"
            f"Role: {agent.role}\n"
            f"Task: {task.title}\n\n"
            f"{task.description or task.title}\n\n"
            "Operate in goal mode: continue until the task is complete or genuinely blocked. "
            f"If approval is required, summarize the approval request for {runtime_config.approval_delegate}; "
            "do not ask the human user directly from the worker agent."
        )
        arguments: dict[str, Any] = {
            "prompt": prompt,
            "developer-instructions": role_prompt,
            "cwd": str(cwd),
            "sandbox": runtime_config.sandbox_mode,
            "approval-policy": runtime_config.approval_policy,
        }
        if runtime_config.model:
            arguments["model"] = runtime_config.model
        config: dict[str, Any] = {
            "model_provider": runtime_config.model_provider,
        }
        if runtime_config.base_url:
            config["model_providers"] = {
                runtime_config.model_provider: {
                    "name": runtime_config.model_provider,
                    "wire_api": "responses",
                    "requires_openai_auth": True,
                    "base_url": runtime_config.base_url,
                }
            }
        arguments["config"] = config
        return arguments


def _extract_codex_tool_output(result: dict[str, Any]) -> tuple[str | None, str]:
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        thread_id = structured.get("threadId")
        content = structured.get("content")
        if isinstance(content, str):
            return str(thread_id) if thread_id is not None else None, content

    direct_thread = result.get("threadId")
    direct_content = result.get("content")
    if isinstance(direct_content, str):
        return str(direct_thread) if direct_thread is not None else None, direct_content

    content_items = result.get("content")
    if isinstance(content_items, list):
        parts = [
            str(item.get("text"))
            for item in content_items
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        ]
        if parts:
            return None, "\n".join(parts)
    return None, str(result)


def runtime_from_environment(
    store: StateStore,
    bus: EventBus,
    layout: WorkspaceLayout | None = None,
    *,
    runtime: str | None = None,
) -> AgentRuntime:
    selected = (os.environ.get("CXW_AGENT_RUNTIME") or runtime or "local-deterministic").strip().lower()
    if selected == "openai-agents":
        return OpenAIAgentsRuntime(store, bus, model=os.environ.get("CXW_OPENAI_AGENT_MODEL"))
    if selected == "codex-mcp":
        if layout is None:
            raise RuntimeError("Codex MCP runtime requires a workspace layout")
        return CodexMcpRuntime(store, bus, layout)
    if selected == "openai-codex":
        if layout is None:
            raise RuntimeError("OpenAI Codex runtime requires a workspace layout")
        from cxw.agents.openai_codex_runtime import OpenAICodexRuntime
        return OpenAICodexRuntime(store, bus, layout, model=os.environ.get("CXW_OPENAI_MODEL") or "gpt-4o")
    return LocalDeterministicRuntime(store, bus)
