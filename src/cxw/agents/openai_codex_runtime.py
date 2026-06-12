"""OpenAI SDK adapter that exposes Codex MCP as a tool to the main orchestrator agent."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cxw.agents.roles import load_role_prompt
from cxw.agents.main_agent_prompt import build_main_agent_system_prompt
from cxw.codex_home import CodexAgentRuntimeConfig, CodexHomeManager
from cxw.codex_mcp import McpStdioClient, codex_mcp_command_from_environment
from cxw.events import EventBus
from cxw.models import AgentRecord, AgentStatus, EventType, Role, TaskRecord
from cxw.project_config import inspect_project_config
from cxw.store import StateStore
from cxw.workspace import WorkspaceLayout


@dataclass
class OpenAICodexRuntime:
    """Runtime that exposes Codex MCP agents as OpenAI SDK tools for main orchestrator."""

    store: StateStore
    bus: EventBus
    layout: WorkspaceLayout
    model: str = "gpt-4o"

    async def dispatch(self, agent: AgentRecord, task: TaskRecord) -> None:
        """Dispatch task - main agent gets codex tool, workers get direct execution."""
        if Role(agent.role) == Role.ORCHESTRATOR:
            await self._dispatch_main_agent(agent, task)
        else:
            await self._dispatch_worker_agent(agent, task)

    async def _dispatch_main_agent(self, agent: AgentRecord, task: TaskRecord) -> None:
        """Main agent runs with OpenAI SDK and has access to codex tool for each worker."""
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise RuntimeError("OpenAI SDK not installed: pip install openai") from exc

        client = AsyncOpenAI()
        workspace = self.store.get_workspace(agent.workspace_id)
        agents_info = [
            {"name": a.name, "role": a.role, "instructions": a.reasoning_summary}
            for a in self.store.list_agents(agent.workspace_id)
        ]

        status = inspect_project_config(self.layout.repo_path, create_template=False)
        workspace_goal = status.config.workspace.goal if status.valid and status.config else "coordinate engineering work"

        system_prompt = build_main_agent_system_prompt(workspace_goal, agents_info)
        tools = self._build_codex_tools()

        self.store.set_agent_status(agent.workspace_id, agent.name, AgentStatus.RUNNING)
        self.store.update_agent_transparency(
            agent.workspace_id,
            agent.name,
            current_goal=task.title,
            current_action="planning and coordinating worker agents",
            reasoning_summary="main orchestrator with codex tool access",
            next_action="analyze requirement, decompose tasks, dispatch workers",
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": self._format_task_prompt(task)},
        ]

        await self.bus.publish(
            EventType.TOOL_CALL,
            agent=agent.name,
            message="main agent starting with codex tools",
            payload={"runtime": "openai-codex", "task_id": task.id, "available_tools": [t["function"]["name"] for t in tools]},
        )

        max_iterations = 50
        for iteration in range(max_iterations):
            response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )

            choice = response.choices[0]
            messages.append(choice.message.model_dump(exclude_unset=True))

            if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
                for tool_call in choice.message.tool_calls:
                    result = await self._handle_tool_call(agent, tool_call)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    })
            elif choice.finish_reason == "stop":
                content = choice.message.content or "Task completed"
                self.store.set_agent_status(agent.workspace_id, agent.name, AgentStatus.COMPLETED)
                await self.bus.publish(
                    EventType.SUMMARY,
                    agent=agent.name,
                    message="main agent task completed",
                    payload={"task_id": task.id, "summary": content, "iterations": iteration + 1},
                )
                return

        self.store.set_agent_status(agent.workspace_id, agent.name, AgentStatus.COMPLETED)
        await self.bus.publish(
            EventType.SUMMARY,
            agent=agent.name,
            message=f"main agent reached iteration limit ({max_iterations})",
            payload={"task_id": task.id, "iterations": max_iterations},
        )

    async def _dispatch_worker_agent(self, agent: AgentRecord, task: TaskRecord) -> None:
        """Worker agent executes via direct Codex MCP call."""
        self.store.set_agent_status(agent.workspace_id, agent.name, AgentStatus.RUNNING)
        runtime_config = self._runtime_config_for(agent.name)
        home = CodexHomeManager(self.layout.repo_path).prepare_agent_home(
            agent.name,
            runtime_config,
            main=False,
            require_auth=True,
        )

        cwd = Path(agent.worktree_path) if agent.worktree_path else self.layout.repo_path
        try:
            async with McpStdioClient(
                codex_mcp_command_from_environment(),
                cwd=cwd,
                env=home.env(),
            ) as client:
                await client.initialize()
                result = await client.call_tool("codex", self._codex_tool_arguments(agent, task, runtime_config, cwd))

            self.store.set_agent_status(agent.workspace_id, agent.name, AgentStatus.COMPLETED)
            thread_id, content = self._extract_codex_output(result)
            await self.bus.publish(
                EventType.SUMMARY,
                agent=agent.name,
                message="worker task completed",
                payload={"task_id": task.id, "thread_id": thread_id, "content": content},
            )
        except Exception as exc:
            self.store.set_agent_status(agent.workspace_id, agent.name, AgentStatus.FAILED)
            await self.bus.publish(
                EventType.FAILED,
                agent=agent.name,
                message=f"worker agent failed: {exc}",
                payload={"task_id": task.id},
            )
            raise

    def _build_codex_tools(self) -> list[dict[str, Any]]:
        """Build OpenAI tool definitions for each worker agent."""
        tools = []
        agents = self.store.list_agents(self.layout.workspace_id)
        for agent in agents:
            if Role(agent.role) == Role.ORCHESTRATOR:
                continue
            tools.append({
                "type": "function",
                "function": {
                    "name": f"codex_{agent.name.replace('-', '_')}",
                    "description": f"Execute a task on {agent.name} ({agent.role}) in isolated worktree. Returns execution result.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "task_description": {
                                "type": "string",
                                "description": "Clear task description for the agent to execute",
                            },
                            "context": {
                                "type": "string",
                                "description": "Additional context, dependencies, or constraints",
                            },
                        },
                        "required": ["task_description"],
                    },
                },
            })
        return tools

    async def _handle_tool_call(self, agent: AgentRecord, tool_call) -> dict[str, Any]:
        """Execute codex tool call for a worker agent."""
        function_name = tool_call.function.name
        if not function_name.startswith("codex_"):
            return {"error": f"unknown tool: {function_name}"}

        worker_name = function_name.replace("codex_", "").replace("_", "-")
        worker = self.store.get_agent(agent.workspace_id, worker_name)
        if worker is None:
            return {"error": f"agent not found: {worker_name}"}

        args = json.loads(tool_call.function.arguments)
        task_desc = args.get("task_description", "")
        context = args.get("context", "")

        await self.bus.publish(
            EventType.TASK_ASSIGNED,
            agent=worker_name,
            message=f"dispatched by {agent.name}: {task_desc[:100]}",
            payload={"parent_agent": agent.name, "task_description": task_desc},
        )

        runtime_config = self._runtime_config_for(worker_name)
        home = CodexHomeManager(self.layout.repo_path).prepare_agent_home(
            worker_name,
            runtime_config,
            main=False,
            require_auth=True,
        )

        cwd = Path(worker.worktree_path) if worker.worktree_path else self.layout.repo_path
        prompt = f"CXW worker: {worker_name}\nRole: {worker.role}\n\n{task_desc}"
        if context:
            prompt += f"\n\nContext:\n{context}"

        try:
            self.store.set_agent_status(worker.workspace_id, worker_name, AgentStatus.RUNNING)
            async with McpStdioClient(
                codex_mcp_command_from_environment(),
                cwd=cwd,
                env=home.env(),
            ) as client:
                await client.initialize()
                result = await client.call_tool("codex", {
                    "prompt": prompt,
                    "developer-instructions": load_role_prompt(Role(worker.role)).prompt,
                    "cwd": str(cwd),
                    "sandbox": runtime_config.sandbox_mode,
                    "approval-policy": runtime_config.approval_policy,
                    "model": runtime_config.model or self.model,
                })

            self.store.set_agent_status(worker.workspace_id, worker_name, AgentStatus.COMPLETED)
            thread_id, content = self._extract_codex_output(result)
            await self.bus.publish(
                EventType.SUMMARY,
                agent=worker_name,
                message="completed subtask",
                payload={"parent_agent": agent.name, "thread_id": thread_id, "content": content},
            )
            return {"status": "completed", "agent": worker_name, "thread_id": thread_id, "output": content}

        except Exception as exc:
            self.store.set_agent_status(worker.workspace_id, worker_name, AgentStatus.FAILED)
            await self.bus.publish(
                EventType.FAILED,
                agent=worker_name,
                message=f"subtask failed: {exc}",
                payload={"parent_agent": agent.name},
            )
            return {"status": "failed", "agent": worker_name, "error": str(exc)}

    def _format_task_prompt(self, task: TaskRecord) -> str:
        return f"""Goal: {task.title}

{task.description or task.title}

Break this down into subtasks, dispatch to appropriate workers, and coordinate execution until complete."""

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
        prompt = f"CXW agent: {agent.name}\nRole: {agent.role}\nTask: {task.title}\n\n{task.description or task.title}"
        return {
            "prompt": prompt,
            "developer-instructions": role_prompt,
            "cwd": str(cwd),
            "sandbox": runtime_config.sandbox_mode,
            "approval-policy": runtime_config.approval_policy,
            "model": runtime_config.model or self.model,
        }

    def _extract_codex_output(self, result: dict[str, Any]) -> tuple[str | None, str]:
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            thread_id = structured.get("threadId")
            content = structured.get("content")
            if isinstance(content, str):
                return str(thread_id) if thread_id else None, content

        direct_thread = result.get("threadId")
        direct_content = result.get("content")
        if isinstance(direct_content, str):
            return str(direct_thread) if direct_thread else None, direct_content

        content_items = result.get("content")
        if isinstance(content_items, list):
            parts = [str(item.get("text")) for item in content_items if isinstance(item, dict) and item.get("text")]
            if parts:
                return None, "\n".join(parts)
        return None, str(result)
