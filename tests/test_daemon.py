from __future__ import annotations

import asyncio

from cxw.daemon import DaemonServer
from cxw.ipc import ping, request, start_server, stream_request


def test_daemon_ipc_status_and_event_replay(tmp_path, monkeypatch):
    monkeypatch.setenv("CXW_HOME", str(tmp_path / "cxw-home"))
    repo = tmp_path / "repo"
    repo.mkdir()

    async def run():
        daemon = DaemonServer(repo)
        await daemon.orchestrator.ensure_initialized()
        server, endpoint = await start_server(daemon.layout, daemon.handle)
        try:
            response = await request(endpoint, {"action": "status"})
            events = [
                item
                async for item in stream_request(endpoint, {"action": "stream_events", "follow": False})
            ]
            return response, events
        finally:
            server.close()
            await server.wait_closed()
            daemon.store.close()

    response, events = asyncio.run(run())

    assert response["ok"] is True
    assert response["snapshot"]["workspace"]["state"] == "COLLECT_REQUIREMENTS"
    assert response["snapshot"]["project_config"]["valid"] is False
    assert [agent["name"] for agent in response["snapshot"]["agents"]] == ["main-1"]
    assert any(item["event"]["type"] == "workspace_created" for item in events)


def test_daemon_health_and_shutdown(tmp_path, monkeypatch):
    monkeypatch.setenv("CXW_HOME", str(tmp_path / "cxw-home"))
    repo = tmp_path / "repo"
    repo.mkdir()

    async def run():
        daemon = DaemonServer(repo)
        await daemon.orchestrator.ensure_initialized()
        server, endpoint = await start_server(daemon.layout, daemon.handle)
        daemon._server = server
        try:
            health = await request(endpoint, {"action": "health"})
            shutdown = await request(endpoint, {"action": "shutdown"})
            await asyncio.sleep(0.1)
            running = await ping(endpoint)
            return health, shutdown, running
        finally:
            server.close()
            await server.wait_closed()
            daemon.store.close()

    health, shutdown, running = asyncio.run(run())

    assert health["ok"] is True
    assert health["health"]["counts"]["agents"] == 1
    assert shutdown["ok"] is True
    assert running is False


def test_daemon_queues_main_agent_message(tmp_path, monkeypatch):
    monkeypatch.setenv("CXW_HOME", str(tmp_path / "cxw-home"))
    repo = tmp_path / "repo"
    repo.mkdir()

    async def run():
        daemon = DaemonServer(repo)
        await daemon.orchestrator.ensure_initialized()
        response = await daemon_request_direct(daemon, {"action": "main_message", "message": "build it"})
        events = daemon.store.list_events(daemon.layout.workspace_id)
        daemon.store.close()
        return response, events

    response, events = asyncio.run(run())

    assert response["ok"] is True
    assert "CXW.toml" in response["reply"]
    main = next(agent for agent in response["snapshot"]["agents"] if agent["name"] == "main-1")
    assert main["current_action"] == "received user message"
    assert any(
        event.agent == "main-1"
        and event.type == "user_message"
        and event.message == "build it"
        for event in events
    )
    assert any(
        event.agent == "main-1"
        and event.type == "agent_message"
        and "CXW.toml" in event.message
        for event in events
    )


def test_daemon_handles_plan_command(tmp_path, monkeypatch):
    monkeypatch.setenv("CXW_HOME", str(tmp_path / "cxw-home"))
    repo = tmp_path / "repo"
    repo.mkdir()

    async def run():
        daemon = DaemonServer(repo)
        await daemon.orchestrator.ensure_initialized()
        response = await daemon_request_direct(
            daemon,
            {
                "action": "plan_command",
                "command": "auto 做一个前后端集成的抽奖项目, 前端 React TailwindCSS, 后端 FastAPI",
            },
        )
        events = daemon.store.list_events(daemon.layout.workspace_id)
        daemon.store.close()
        return response, events

    response, events = asyncio.run(run())

    assert response["ok"] is True
    assert "已生成 `CXW.toml` 草案" in response["reply"]
    assert response["snapshot"]["project_config"]["valid"] is True
    assert any(event.type == "user_message" and event.message.startswith("/plan auto") for event in events)
    assert any(event.type == "agent_message" and event.payload["command"] == "plan" for event in events)


def test_daemon_handles_run_plan_command(tmp_path, monkeypatch):
    monkeypatch.setenv("CXW_HOME", str(tmp_path / "cxw-home"))
    repo = tmp_path / "repo"
    repo.mkdir()

    async def run():
        daemon = DaemonServer(repo)
        calls = []

        async def fake_run_plan(runtime_name=None):
            calls.append(runtime_name)
            return "running"

        daemon.orchestrator.run_plan = fake_run_plan
        response = await daemon_request_direct(
            daemon,
            {"action": "run_plan", "runtime": "local-deterministic"},
        )
        daemon.store.close()
        return response, calls

    response, calls = asyncio.run(run())

    assert response["ok"] is True
    assert response["reply"] == "running"
    assert calls == ["local-deterministic"]


async def daemon_request_direct(daemon: DaemonServer, payload: dict):
    class _Writer:
        def __init__(self):
            self.items = []

        def write(self, data):
            self.items.append(data)

        async def drain(self):
            return None

    writer = _Writer()
    await daemon.handle(payload, writer)
    import json

    return json.loads(b"".join(writer.items).decode("utf-8").splitlines()[0])
