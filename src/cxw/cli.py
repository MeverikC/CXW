from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from cxw.backup import create_workspace_backup, restore_workspace_backup
from cxw.daemon import daemon_request, ensure_daemon
from cxw.errors import CXWError
from cxw.ipc import ping, read_endpoint, request, stream_request
from cxw.project_config import inspect_project_config
from cxw.registry import list_workspace_summaries, read_workspace_summary
from cxw.serialization import dumps_json
from cxw.ui import (
    format_event_line,
    render_health,
    render_status,
    render_summaries,
    render_workspace_info,
    render_workspaces,
)
from cxw.workspace import WorkspaceLayout, cxw_home

console = Console()

app = typer.Typer(
    add_completion=False,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    help="CXW local-first multi-agent orchestration workspace.",
)


@app.callback(invoke_without_command=True)
def cxw(
    ctx: typer.Context,
    args: list[str] = typer.Argument(None, help="CXW command arguments."),
) -> None:
    """Dispatch CXW commands through the workspace daemon."""
    try:
        asyncio.run(_dispatch(list(args or []) + list(ctx.args)))
    except KeyboardInterrupt:
        raise typer.Exit(130) from None
    except CXWError as exc:
        console.print(f"[red]cxw:[/red] {exc}")
        raise typer.Exit(1) from None
    except Exception as exc:
        console.print(f"[red]cxw:[/red] {exc}")
        raise typer.Exit(1) from None


async def _dispatch(args: list[str]) -> None:
    json_output, args = _extract_json_flag(args)
    interactive_mode, args = _extract_interactive_mode(args)
    if not args:
        console.print("Usage: cxw <repo> [status|plan|run|logs|agent|stop|resume|final-approve]")
        console.print("       cxw workspaces")
        console.print("       cxw clean [<workspace_id>|all]")
        console.print("       cxw <repo> config-check|daemon-health|daemon-stop|workspace-info")
        return

    if args[0] == "workspaces":
        summaries = await list_workspace_summaries()
        if json_output:
            _print_json({"ok": True, "workspaces": summaries})
        else:
            render_workspaces(console, summaries)
        return

    if args[0] == "clean":
        await _clean_workspaces(args[1:], json_output)
        return

    if args[0] == "restore":
        if len(args) < 3:
            raise typer.BadParameter("restore requires an archive path and target repo path")
        result = restore_workspace_backup(args[1], args[2])
        if json_output:
            _print_json({"ok": True, "restore": result})
        else:
            console.print(f"Restored workspace {result.target_workspace_id[:12]}")
            console.print(f"Repository: {result.target_repo_path}")
            console.print(f"Workspace: {result.target_workspace_root}")
            console.print(f"Files: {result.restored_file_count}")
        return

    repo = Path(args[0])
    command_args = args[1:]
    if not command_args:
        if not json_output and _should_run_interactive(interactive_mode):
            from cxw.tui import run_workspace_shell

            await run_workspace_shell(repo)
            return
        else:
            response = await daemon_request(repo, {"action": "launch"})
        if json_output:
            _print_json(response)
        elif not sys.stdin.isatty() or not sys.stdout.isatty():
            render_status(console, response["snapshot"])
        return

    command = command_args[0]
    if command in {"shell", "interactive"}:
        if json_output:
            raise typer.BadParameter("interactive shell does not support --json")
        from cxw.tui import run_workspace_shell

        await run_workspace_shell(repo)
        return
    if command == "status":
        response = await daemon_request(repo, {"action": "status"})
        if json_output:
            _print_json(response)
        else:
            render_status(console, response["snapshot"])
        return
    if command == "plan":
        response = await daemon_request(
            repo, {"action": "plan_command", "command": " ".join(command_args[1:])}
        )
        if json_output:
            _print_json(response)
        else:
            console.print(str(response.get("reply") or ""))
        return
    if command == "config-check":
        status = inspect_project_config(repo, create_template=True)
        if json_output:
            _print_json({"ok": status.valid, "project_config": status.to_snapshot()})
        else:
            _render_config_check(status.to_snapshot())
        return
    if command == "logs":
        agent = command_args[1] if len(command_args) > 1 else None
        await _stream(repo, agent=agent, follow=False, json_output=json_output)
        return
    if command == "stop":
        if len(command_args) < 2:
            raise typer.BadParameter("stop requires an agent name")
        response = await daemon_request(repo, {"action": "stop_agent", "agent": command_args[1]})
        if json_output:
            _print_json(response)
        else:
            render_status(console, response["snapshot"])
        return
    if command == "resume":
        response = await daemon_request(repo, {"action": "resume"})
        if json_output:
            _print_json(response)
        else:
            render_status(console, response["snapshot"])
        return
    if command == "run":
        runtime, remaining = _extract_runtime_option(command_args[1:])
        if remaining:
            raise typer.BadParameter("run only accepts --runtime <name>")
        payload: dict[str, Any] = {"action": "run_plan"}
        if runtime:
            payload["runtime"] = runtime
        response = await daemon_request(repo, payload)
        if json_output:
            _print_json(response)
        else:
            if response.get("reply"):
                console.print(str(response["reply"]))
            render_status(console, response["snapshot"])
        return
    if command == "approve-plan":
        response = await daemon_request(repo, {"action": "approve_plan"})
        if json_output:
            _print_json(response)
        else:
            render_status(console, response["snapshot"])
        return
    if command == "final-approve":
        response = await daemon_request(repo, {"action": "final_approve"})
        if json_output:
            _print_json(response)
        else:
            render_status(console, response["snapshot"])
        return
    if command == "daemon-health":
        await _daemon_health(repo, json_output=json_output)
        return
    if command == "daemon-stop":
        await _daemon_stop(repo, json_output=json_output)
        return
    if command == "workspace-info":
        await _workspace_info(repo, json_output=json_output)
        return
    if command in {"summaries", "merge-plan"}:
        response = await daemon_request(repo, {"action": "summaries"})
        if json_output:
            _print_json(response)
        else:
            render_summaries(console, response["summaries"])
        return
    if command == "backup":
        archive = command_args[1] if len(command_args) > 1 else None
        result = create_workspace_backup(repo, archive)
        if json_output:
            _print_json({"ok": True, "backup": result})
        else:
            console.print(f"Backup created: {result.archive_path}")
            console.print(f"Workspace: {result.manifest.source_workspace_id[:12]}")
            console.print(f"Files: {result.file_count}")
        return

    await _stream(repo, agent=command, follow=True, json_output=json_output)


def _extract_json_flag(args: list[str]) -> tuple[bool, list[str]]:
    return "--json" in args, [arg for arg in args if arg != "--json"]


def _extract_interactive_mode(args: list[str]) -> tuple[str, list[str]]:
    mode = "auto"
    remaining: list[str] = []
    for arg in args:
        if arg in {"--interactive", "-i"}:
            mode = "force"
        elif arg == "--no-interactive":
            mode = "off"
        else:
            remaining.append(arg)
    return mode, remaining


def _extract_runtime_option(args: list[str]) -> tuple[str | None, list[str]]:
    runtime: str | None = None
    remaining: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--runtime":
            if index + 1 >= len(args):
                raise typer.BadParameter("--runtime requires a value")
            runtime = args[index + 1]
            index += 2
            continue
        if arg.startswith("--runtime="):
            runtime = arg.split("=", 1)[1]
            index += 1
            continue
        remaining.append(arg)
        index += 1
    return runtime, remaining


def _should_run_interactive(mode: str) -> bool:
    if mode == "off":
        return False
    if mode == "force":
        return True
    return sys.stdin.isatty() and sys.stdout.isatty()


def _print_json(value: Any) -> None:
    sys.stdout.write(dumps_json(value) + "\n")


async def _clean_workspaces(args: list[str], json_output: bool) -> None:
    """Clean workspace caches."""
    import shutil

    if not args:
        console.print("Usage: cxw clean <workspace_id>|all")
        console.print("\nList workspaces with: cxw workspaces")
        return

    target = args[0]
    home = cxw_home()
    workspaces_dir = home / "workspaces"

    if not workspaces_dir.exists():
        if json_output:
            _print_json({"ok": True, "removed": 0})
        else:
            console.print("No workspaces found")
        return

    if target == "all":
        count = len(list(workspaces_dir.iterdir()))
        shutil.rmtree(workspaces_dir)
        workspaces_dir.mkdir(parents=True, exist_ok=True)
        if json_output:
            _print_json({"ok": True, "removed": count})
        else:
            console.print(f"Removed {count} workspace(s)")
    else:
        workspace_path = workspaces_dir / target
        if not workspace_path.exists():
            if json_output:
                _print_json({"ok": False, "error": "workspace not found"})
            else:
                console.print(f"Workspace not found: {target}")
            raise typer.Exit(1)
        shutil.rmtree(workspace_path)
        if json_output:
            _print_json({"ok": True, "removed": 1, "workspace_id": target})
        else:
            console.print(f"Removed workspace: {target[:12]}")


def _render_config_check(status: dict[str, Any]) -> None:
    path = status.get("path") or ""
    if status.get("valid"):
        workspace = status.get("workspace") or {}
        console.print(f"[green]CXW project config valid:[/green] {path}")
        console.print(f"Plan: {workspace.get('name') or ''}")
        console.print(f"Roles: {len(status.get('roles') or [])}")
        console.print(f"Tasks: {len(status.get('tasks') or [])}")
        return
    if status.get("created_template"):
        console.print(f"[yellow]CXW project config template created:[/yellow] {path}")
    elif status.get("exists"):
        console.print(f"[red]CXW project config invalid:[/red] {path}")
    else:
        console.print(f"[red]CXW project config missing:[/red] {path}")
    for error in status.get("errors") or []:
        console.print(f"- {error}")


async def _stream(repo: Path, *, agent: str | None, follow: bool, json_output: bool) -> None:
    endpoint = await ensure_daemon(repo)
    payload: dict[str, Any] = {"action": "stream_events", "agent": agent, "follow": follow}
    async for item in stream_request(endpoint, payload):
        event = item.get("event")
        if isinstance(event, dict):
            if json_output:
                _print_json(event)
            else:
                console.print(format_event_line(event))


async def _daemon_health(repo: Path, *, json_output: bool) -> None:
    layout = WorkspaceLayout.from_repo(repo)
    endpoint = read_endpoint(layout)
    if endpoint is None or not await ping(endpoint):
        summary = await read_workspace_summary(layout.root, check_daemon=False)
        if json_output:
            _print_json({"ok": True, "running": False, "workspace": summary, "cxw_home": cxw_home()})
        else:
            console.print(f"Daemon stopped for workspace {summary.workspace_id[:12]}")
            console.print(f"CXW home: {cxw_home()}")
        return
    response = await request(endpoint, {"action": "health"})
    if json_output:
        _print_json(response)
    else:
        render_health(console, response["health"])


async def _daemon_stop(repo: Path, *, json_output: bool) -> None:
    layout = WorkspaceLayout.from_repo(repo)
    endpoint = read_endpoint(layout)
    if endpoint is None or not await ping(endpoint):
        if json_output:
            _print_json({"ok": True, "running": False, "workspace_id": layout.workspace_id})
        else:
            console.print(f"Daemon already stopped for workspace {layout.workspace_id[:12]}")
        return
    response = await request(endpoint, {"action": "shutdown"})
    if json_output:
        _print_json(response)
    else:
        console.print(str(response.get("message") or "daemon shutdown requested"))


async def _workspace_info(repo: Path, *, json_output: bool) -> None:
    layout = WorkspaceLayout.from_repo(repo)
    endpoint = read_endpoint(layout)
    if endpoint is not None and await ping(endpoint):
        response = await request(endpoint, {"action": "workspace_info"})
        if json_output:
            _print_json(response)
        else:
            render_workspace_info(console, response["workspace_info"])
        return
    summary = await read_workspace_summary(layout.root, check_daemon=False)
    if json_output:
        _print_json({"ok": True, "running": False, "workspace": summary})
    else:
        render_workspaces(console, [summary])


def main() -> None:
    app()


if __name__ == "__main__":
    main()
