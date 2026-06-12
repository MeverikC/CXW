from __future__ import annotations

import asyncio
import sys

from cxw.agents.runtime import CodexMcpRuntime, runtime_from_environment
from cxw.codex_mcp import McpStdioClient
from cxw.events import EventBus
from cxw.models import AgentRecord, Role, TaskRecord, WorkspaceRecord
from cxw.store import StateStore
from cxw.workspace import WorkspaceLayout


FAKE_MCP_SERVER = r'''
import json
import sys


CURRENT_FRAMING = "jsonl"


def read_message():
    global CURRENT_FRAMING
    content_length = None
    first = sys.stdin.buffer.readline()
    if not first:
        return None
    if not first.lower().startswith(b"content-length:"):
        CURRENT_FRAMING = "jsonl"
        return json.loads(first.decode("utf-8"))
    CURRENT_FRAMING = "content-length"
    _, _, value = first.strip().decode("ascii").partition(":")
    content_length = int(value.strip())
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        stripped = line.strip()
        if not stripped:
            break
        key, _, value = stripped.decode("ascii").partition(":")
        if key.lower() == "content-length":
            content_length = int(value.strip())
    if content_length is None:
        raise RuntimeError("missing content length")
    return json.loads(sys.stdin.buffer.read(content_length).decode("utf-8"))


def write_message(message):
    payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
    if CURRENT_FRAMING == "content-length":
        sys.stdout.buffer.write(b"Content-Length: " + str(len(payload)).encode("ascii") + b"\r\n\r\n")
        sys.stdout.buffer.write(payload)
    else:
        sys.stdout.buffer.write(payload + b"\n")
    sys.stdout.buffer.flush()


while True:
    message = read_message()
    if message is None:
        break
    if "id" not in message:
        continue
    if message["method"] == "initialize":
        write_message({
            "jsonrpc": "2.0",
            "id": message["id"],
            "result": {
                "protocolVersion": message["params"]["protocolVersion"],
                "serverInfo": {"name": "fake-codex", "version": "0.0.1"},
                "capabilities": {"tools": {}},
            },
        })
    elif message["method"] == "tools/list":
        write_message({
            "jsonrpc": "2.0",
            "id": message["id"],
            "result": {"tools": [{"name": "codex", "description": "Run Codex"}]},
        })
    elif message["method"] == "tools/call":
        arguments = message["params"]["arguments"]
        write_message({
            "jsonrpc": "2.0",
            "id": message["id"],
            "result": {
                "structuredContent": {
                    "threadId": "thread-1",
                    "content": "completed " + arguments["prompt"].splitlines()[0],
                },
                "content": [{"type": "text", "text": "completed"}],
            },
        })
    else:
        write_message({
            "jsonrpc": "2.0",
            "id": message["id"],
            "error": {"code": -32601, "message": "unknown method"},
        })
'''


def _write_fake_server(tmp_path):
    path = tmp_path / "fake_mcp_server.py"
    path.write_text(FAKE_MCP_SERVER, encoding="utf-8")
    return path


def _source_codex_home(tmp_path):
    source = tmp_path / "source-codex"
    source.mkdir()
    (source / "auth.json").write_text('{"token":"secret"}\n', encoding="utf-8")
    (source / "config.toml").write_text('model = "gpt-5.5"\n', encoding="utf-8")
    return source


def test_mcp_stdio_client_initializes_and_lists_tools(tmp_path):
    server = _write_fake_server(tmp_path)

    async def run():
        async with McpStdioClient([sys.executable, str(server)], framing="content-length") as client:
            initialized = await client.initialize()
            tools = await client.list_tools()
            return initialized, tools

    initialized, tools = asyncio.run(run())

    assert initialized["serverInfo"]["name"] == "fake-codex"
    assert tools == [{"name": "codex", "description": "Run Codex"}]


def test_mcp_stdio_client_defaults_to_codex_jsonl_framing(tmp_path):
    server = _write_fake_server(tmp_path)

    async def run():
        async with McpStdioClient([sys.executable, str(server)]) as client:
            initialized = await client.initialize()
            tools = await client.list_tools()
            return initialized, tools

    initialized, tools = asyncio.run(run())

    assert initialized["serverInfo"]["name"] == "fake-codex"
    assert tools[0]["name"] == "codex"


def test_codex_mcp_runtime_prepares_home_and_publishes_probe_events(tmp_path, monkeypatch):
    monkeypatch.setenv("CXW_HOME", str(tmp_path / "cxw-home"))
    monkeypatch.setenv("CODEX_HOME", str(_source_codex_home(tmp_path)))
    monkeypatch.setenv("CXW_AGENT_RUNTIME", "codex-mcp")
    monkeypatch.setenv("CXW_CODEX_MCP_COMMAND", f"{sys.executable} {_write_fake_server(tmp_path)}")

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "CXW.toml").write_text(
        """
[workspace]
name = "Runtime"
goal = "Probe Codex MCP."

[defaults.codex]
model = "gpt-5.5"
base_url = "http://127.0.0.1:15721/v1"

[[agents]]
name = "planner-1"
role = "planner"
instructions = "Plan the work."

[[agents]]
name = "engineer-1"
role = "backend-coder"
instructions = "Implement the work."

[[tasks]]
title = "Implement feature"
description = "Do the work."
assigned_agent = "engineer-1"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    layout = WorkspaceLayout.from_repo(repo)
    store = StateStore(layout)
    store.upsert_workspace(WorkspaceRecord(id=layout.workspace_id, repo_path=str(repo)))
    agent = store.upsert_agent(
        AgentRecord(
            workspace_id=layout.workspace_id,
            name="engineer-1",
            role=Role.BACKEND_CODER,
            worktree_path=str(repo),
        )
    )
    task = store.create_task(
        TaskRecord(
            workspace_id=layout.workspace_id,
            title="Implement feature",
            description="Do the work.",
            assigned_agent="engineer-1",
        )
    )
    bus = EventBus(store, layout.workspace_id)
    runtime = runtime_from_environment(store, bus, layout)

    asyncio.run(runtime.dispatch(agent, task))

    events = store.list_events(layout.workspace_id)
    home = repo / ".codex" / "cxw" / "agents" / "engineer-1"
    assert (home / "auth.json").read_text(encoding="utf-8") == '{"token":"secret"}\n'
    assert any(event.type == "tool_call" and event.agent == "engineer-1" for event in events)
    summary = next(event for event in events if event.type == "summary")
    assert summary.payload["tool_count"] == 1
    assert summary.payload["tools"][0]["name"] == "codex"
    assert summary.payload["thread_id"] == "thread-1"
    assert summary.payload["content"] == "completed CXW agent: engineer-1"
    assert not any("secret" in str(event.payload) for event in events)
    store.close()


def test_runtime_selection_accepts_explicit_runtime_without_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("CXW_AGENT_RUNTIME", raising=False)
    monkeypatch.setenv("CXW_HOME", str(tmp_path / "cxw-home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    layout = WorkspaceLayout.from_repo(repo)
    store = StateStore(layout)
    bus = EventBus(store, layout.workspace_id)

    runtime = runtime_from_environment(store, bus, layout, runtime="codex-mcp")

    assert isinstance(runtime, CodexMcpRuntime)
    store.close()
