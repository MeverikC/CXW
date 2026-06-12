from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from cxw.errors import DaemonError
from cxw.events import EventBus
from cxw.ipc import Endpoint, ping, read_endpoint, request, send_json, start_server
from cxw.models import EventType
from cxw.orchestrator import Orchestrator
from cxw.serialization import to_jsonable
from cxw.store import StateStore
from cxw.summaries import SummaryService
from cxw.workspace import WorkspaceLayout


class DaemonServer:
    def __init__(self, repo_path: str | os.PathLike[str]):
        self.layout = WorkspaceLayout.from_repo(repo_path)
        self.layout.ensure()
        self.store = StateStore(self.layout)
        self.bus = EventBus(self.store, self.layout.workspace_id)
        self.orchestrator = Orchestrator(self.layout, self.store, self.bus)
        self._server: asyncio.AbstractServer | None = None
        self._shutdown_event: asyncio.Event | None = None

    async def run(self) -> None:
        self._shutdown_event = asyncio.Event()
        await self.orchestrator.ensure_initialized()
        await self.bus.publish(
            EventType.DAEMON_STARTED,
            agent="orchestrator",
            message="daemon listening for workspace commands",
            payload={"pid": os.getpid()},
        )
        self._server, endpoint = await start_server(self.layout, self.handle)
        await self.bus.publish(
            EventType.SUMMARY,
            agent="orchestrator",
            message="daemon endpoint ready",
            payload=endpoint.to_dict(),
        )
        async with self._server:
            await self._shutdown_event.wait()

    async def handle(self, payload: dict[str, Any], writer: asyncio.StreamWriter) -> None:
        action = payload.get("action")
        if action == "ping":
            await send_json(writer, {"ok": True, "workspace_id": self.layout.workspace_id})
            return
        if action == "health":
            await send_json(writer, {"ok": True, "health": self.health()})
            return
        if action == "workspace_info":
            await send_json(writer, {"ok": True, "workspace_info": self.workspace_info()})
            return
        if action == "summaries":
            summaries = await SummaryService(
                self.store, self.bus, self.layout.workspace_id
            ).generate()
            await send_json(writer, {"ok": True, "summaries": summaries})
            return
        if action == "shutdown":
            await self.bus.publish(
                EventType.SUMMARY,
                agent="orchestrator",
                message="daemon shutdown requested",
                payload={"pid": os.getpid()},
            )
            await send_json(writer, {"ok": True, "message": "daemon shutdown requested"})
            self._schedule_shutdown()
            return
        if action == "launch":
            await self.orchestrator.ensure_initialized()
            await send_json(writer, {"ok": True, "snapshot": self.snapshot()})
            return
        if action == "status":
            await send_json(writer, {"ok": True, "snapshot": self.snapshot()})
            return
        if action == "resume":
            await self.orchestrator.resume()
            await send_json(writer, {"ok": True, "snapshot": self.snapshot()})
            return
        if action == "run_plan":
            runtime = payload.get("runtime")
            if runtime is not None and not isinstance(runtime, str):
                raise DaemonError("runtime must be a string")
            reply = await self.orchestrator.run_plan(runtime_name=runtime)
            await send_json(writer, {"ok": True, "reply": reply, "snapshot": self.snapshot()})
            return
        if action == "approve_plan":
            await self.orchestrator.approve_plan()
            await send_json(writer, {"ok": True, "snapshot": self.snapshot()})
            return
        if action == "final_approve":
            await self.orchestrator.final_approve()
            await send_json(writer, {"ok": True, "snapshot": self.snapshot()})
            return
        if action == "stop_agent":
            agent = self._required(payload, "agent")
            await self.orchestrator.stop_agent(agent)
            await send_json(writer, {"ok": True, "snapshot": self.snapshot()})
            return
        if action == "main_message":
            message = self._required(payload, "message")
            reply = await self.orchestrator.queue_main_message(message)
            await send_json(writer, {"ok": True, "reply": reply, "snapshot": self.snapshot()})
            return
        if action == "plan_command":
            command = str(payload.get("command") or "")
            reply = await self.orchestrator.handle_plan_command(command)
            await send_json(writer, {"ok": True, "reply": reply, "snapshot": self.snapshot()})
            return
        if action == "stream_events":
            await self._stream_events(payload, writer)
            return
        await send_json(writer, {"ok": False, "error": f"unknown action: {action}"})

    def snapshot(self) -> dict[str, Any]:
        workspace = self.store.get_workspace(self.layout.workspace_id)
        return to_jsonable(
            {
                "workspace": workspace,
                "agents": self.store.list_agents(self.layout.workspace_id),
                "tasks": self.store.list_tasks(self.layout.workspace_id),
                "recent_events": self.store.list_events(
                    self.layout.workspace_id, after_sequence=0, limit=20
                ),
                "state_transitions": self.store.list_transitions(self.layout.workspace_id),
                "commits": self.store.list_commits(self.layout.workspace_id),
                "reviews": self.store.list_reviews(self.layout.workspace_id),
                "project_config": self.orchestrator.project_config_status().to_snapshot(),
                "paths": {
                    "repo": str(self.layout.repo_path),
                    "workspace": str(self.layout.root),
                    "db": str(self.layout.db_path),
                    "events": str(self.layout.events_path),
                },
            }
        )

    def health(self) -> dict[str, Any]:
        workspace = self.store.get_workspace(self.layout.workspace_id)
        return to_jsonable(
            {
                "pid": os.getpid(),
                "workspace_id": self.layout.workspace_id,
                "repo_path": str(self.layout.repo_path),
                "state": workspace.state if workspace else None,
                "counts": {
                    "agents": self.store.count_rows("agents", self.layout.workspace_id),
                    "tasks": self.store.count_rows("tasks", self.layout.workspace_id),
                    "events": self.store.count_rows("events", self.layout.workspace_id),
                    "state_transitions": self.store.count_rows(
                        "state_transitions", self.layout.workspace_id
                    ),
                    "commits": self.store.count_rows("commits", self.layout.workspace_id),
                    "reviews": self.store.count_rows("reviews", self.layout.workspace_id),
                },
                "paths": {
                    "workspace": str(self.layout.root),
                    "db": str(self.layout.db_path),
                    "events": str(self.layout.events_path),
                    "endpoint": str(self.layout.endpoint_path),
                },
            }
        )

    def workspace_info(self) -> dict[str, Any]:
        return to_jsonable(
            {
                "health": self.health(),
                "snapshot": self.snapshot(),
            }
        )

    async def _stream_events(
        self, payload: dict[str, Any], writer: asyncio.StreamWriter
    ) -> None:
        agent = payload.get("agent")
        follow = bool(payload.get("follow", True))
        after_sequence = int(payload.get("after_sequence") or 0)
        async for event in self.bus.stream(
            agent=agent, after_sequence=after_sequence, follow=follow
        ):
            await send_json(writer, {"ok": True, "event": to_jsonable(event)})

    @staticmethod
    def _required(payload: dict[str, Any], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise DaemonError(f"missing required field: {key}")
        return value

    def _schedule_shutdown(self) -> None:
        async def shutdown() -> None:
            await asyncio.sleep(0.05)
            if self._server is not None:
                self._server.close()
                await self._server.wait_closed()
            if self._shutdown_event is not None:
                self._shutdown_event.set()

        asyncio.create_task(shutdown())


async def ensure_daemon(repo_path: str | os.PathLike[str], *, timeout: float = 8.0) -> Endpoint:
    layout = WorkspaceLayout.from_repo(repo_path)
    layout.ensure()
    existing = read_endpoint(layout)
    if existing is not None and await ping(existing):
        return existing

    stdout = (layout.logs_dir / "daemon.stdout.log").open("ab")
    stderr = (layout.logs_dir / "daemon.stderr.log").open("ab")
    env = os.environ.copy()
    src_path = str(Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = os.pathsep.join(
        [src_path, env["PYTHONPATH"]] if env.get("PYTHONPATH") else [src_path]
    )
    kwargs: dict[str, Any] = {
        "stdout": stdout,
        "stderr": stderr,
        "stdin": subprocess.DEVNULL,
        "env": env,
        "cwd": str(layout.repo_path),
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(
        [sys.executable, "-m", "cxw.daemon", str(layout.repo_path)],
        **kwargs,
    )

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        await asyncio.sleep(0.1)
        endpoint = read_endpoint(layout)
        if endpoint is not None and await ping(endpoint):
            return endpoint
    raise DaemonError(f"daemon did not become ready for {layout.repo_path}")


async def daemon_request(repo_path: str | os.PathLike[str], payload: dict[str, Any]) -> dict[str, Any]:
    endpoint = await ensure_daemon(repo_path)
    return await request(endpoint, payload)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m cxw.daemon")
    parser.add_argument("repo", type=Path)
    args = parser.parse_args(argv)
    asyncio.run(DaemonServer(args.repo).run())


if __name__ == "__main__":
    main()
