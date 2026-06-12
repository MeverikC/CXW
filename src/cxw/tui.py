from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel

from cxw.daemon import daemon_request
from cxw.ui import render_status


class WorkspaceShell:
    """Prompt-toolkit backed terminal shell for a CXW workspace."""

    def __init__(self, repo: str | Path, console: Console | None = None):
        self.repo = Path(repo)
        self.console = console or Console()

    async def run(self) -> None:
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.patch_stdout import patch_stdout
        except ImportError as exc:
            raise RuntimeError(
                "prompt_toolkit is required for interactive mode. "
                "Install CXW with `python -m pip install -e .`."
            ) from exc

        response = await daemon_request(self.repo, {"action": "launch"})
        snapshot = response["snapshot"]
        self._render_compact(snapshot)
        self._render_recent_conversation(snapshot)
        self._render_help()

        session = PromptSession()
        while True:
            main_agent = _main_agent_name(snapshot)
            with patch_stdout():
                text = (await session.prompt_async(f"{main_agent}> ")).strip()
            if not text:
                continue
            if text in {"/quit", "/exit"}:
                return
            snapshot = await self._handle_input(text)

    async def _handle_input(self, text: str) -> dict[str, Any]:
        if text in {"/status", "/dashboard"}:
            response = await daemon_request(self.repo, {"action": "status"})
            snapshot = response["snapshot"]
            self._render_status(snapshot)
            return snapshot
        if _is_plan_command(text):
            command = _plan_command_args(text)
            response = await daemon_request(
                self.repo, {"action": "plan_command", "command": command}
            )
            snapshot = response["snapshot"]
            self._render_exchange(text, str(response.get("reply") or ""), _main_agent_name(snapshot))
            return snapshot
        if _is_run_command(text):
            response = await daemon_request(self.repo, _run_payload(text))
            snapshot = response["snapshot"]
            self._render_exchange(text, str(response.get("reply") or ""), _main_agent_name(snapshot))
            return snapshot
        if text == "/clear":
            response = await daemon_request(self.repo, {"action": "status"})
            snapshot = response["snapshot"]
            self._render_compact(snapshot)
            self._render_help()
            return snapshot
        elif text == "/approve":
            response = await daemon_request(self.repo, {"action": "approve_plan"})
            snapshot = response["snapshot"]
            self._render_compact(snapshot)
            self.console.print("[green]Legacy approve command completed. Prefer /run.[/green]")
            return snapshot
        elif text == "/final":
            response = await daemon_request(self.repo, {"action": "final_approve"})
            snapshot = response["snapshot"]
            self._render_compact(snapshot)
            self.console.print("[green]Final approval command completed.[/green]")
            return snapshot
        elif text == "/resume":
            response = await daemon_request(self.repo, {"action": "resume"})
            snapshot = response["snapshot"]
            self._render_compact(snapshot)
            self.console.print("[green]Workspace resume command completed.[/green]")
            return snapshot
        else:
            response = await daemon_request(self.repo, {"action": "main_message", "message": text})
            snapshot = response["snapshot"]
            self._render_exchange(text, str(response.get("reply") or ""), _main_agent_name(snapshot))
            return snapshot

    def _render_status(self, snapshot: dict[str, Any]) -> None:
        self.console.clear()
        render_status(self.console, snapshot)

    def _render_compact(self, snapshot: dict[str, Any]) -> None:
        self.console.clear()
        workspace = snapshot.get("workspace") or {}
        project_config = snapshot.get("project_config") or {}
        agents = snapshot.get("agents") or []
        tasks = snapshot.get("tasks") or []
        repo = (snapshot.get("paths") or {}).get("repo") or workspace.get("repo_path") or self.repo
        config_state = "valid" if project_config.get("valid") else "needs plan"
        text = (
            f"Repo: {repo}\n"
            f"State: {workspace.get('state') or 'unknown'} | Config: {config_state} | "
            f"Agents: {len(agents)} | Tasks: {len(tasks)}\n"
            f"Main: {_main_agent_name(snapshot)}"
        )
        self.console.print(Panel(text, title="CXW Workspace", expand=True))

    def _render_recent_conversation(self, snapshot: dict[str, Any]) -> None:
        events = _conversation_events(snapshot)
        if not events:
            return
        self.console.print("[bold]Recent Conversation[/bold]")
        for event in events[-6:]:
            role = "You" if event.get("type") == "user_message" else str(event.get("agent") or "agent")
            self.console.print(f"[bold]{role}:[/bold] {_event_message(event)}")

    def _render_exchange(self, user_text: str, reply: str, agent_name: str) -> None:
        self.console.print(f"[bold]You:[/bold] {user_text}")
        self.console.print(f"[bold]{agent_name}:[/bold] {reply}")

    def _render_help(self) -> None:
        self.console.print(
            "[dim]Commands: /plan, /run, /status, /dashboard, /final, /resume, /clear, /quit. "
            "Other input is sent to the main agent.[/dim]"
        )


def _main_agent_name(snapshot: dict[str, Any]) -> str:
    project_config = snapshot.get("project_config") or {}
    main_agent = project_config.get("main_agent") or {}
    configured = main_agent.get("name")
    if configured:
        return str(configured)
    for agent in snapshot.get("agents") or []:
        if agent.get("role") == "orchestrator":
            return str(agent.get("name") or "main-1")
    return "main-1"


def _conversation_events(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        event
        for event in snapshot.get("recent_events") or []
        if event.get("type") in {"user_message", "agent_message"}
    ]


def _event_message(event: dict[str, Any]) -> str:
    message = event.get("message")
    return str(message) if message is not None else ""


def _is_plan_command(text: str) -> bool:
    return text == "/plan" or text.startswith("/plan ")


def _plan_command_args(text: str) -> str:
    return text[len("/plan") :].strip()


def _is_run_command(text: str) -> bool:
    return text == "/run" or text.startswith("/run ")


def _run_payload(text: str) -> dict[str, Any]:
    args = text[len("/run") :].strip().split()
    payload: dict[str, Any] = {"action": "run_plan"}
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--runtime":
            if index + 1 < len(args):
                payload["runtime"] = args[index + 1]
                index += 2
                continue
            break
        if arg.startswith("--runtime="):
            payload["runtime"] = arg.split("=", 1)[1]
        index += 1
    return payload


async def run_workspace_shell(repo: str | Path) -> None:
    await WorkspaceShell(repo).run()
