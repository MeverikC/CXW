from __future__ import annotations

import asyncio
import json
import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cxw.errors import CodexRuntimeError


MCP_PROTOCOL_VERSION = "2024-11-05"


@dataclass
class McpStdioClient:
    command: list[str]
    cwd: Path | None = None
    env: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 20.0
    framing: str = "jsonl"

    def __post_init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._next_id = 1

    async def __aenter__(self) -> "McpStdioClient":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def start(self) -> None:
        if self._process is not None:
            return
        env = os.environ.copy()
        env.update(self.env)
        try:
            self._process = await asyncio.create_subprocess_exec(
                *self.command,
                cwd=str(self.cwd) if self.cwd else None,
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise CodexRuntimeError(f"failed to start MCP server {self.command!r}: {exc}") from exc

    async def close(self) -> None:
        process = self._process
        if process is None:
            return
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        self._process = None

    async def initialize(self) -> dict[str, Any]:
        result = await self.request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "cxw", "version": "0.1.0"},
            },
        )
        await self.notify("notifications/initialized", {})
        return result

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self.request("tools/list", {})
        tools = result.get("tools") if isinstance(result, dict) else None
        return tools if isinstance(tools, list) else []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self.request("tools/call", {"name": name, "arguments": arguments})

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        message_id = self._next_id
        self._next_id += 1
        await self._send({"jsonrpc": "2.0", "id": message_id, "method": method, "params": params or {}})

        while True:
            try:
                response = await asyncio.wait_for(self._read(), timeout=self.timeout_seconds)
            except asyncio.TimeoutError as exc:
                stderr = await self._read_stderr()
                detail = f": {stderr}" if stderr else ""
                raise CodexRuntimeError(f"MCP {method} timed out{detail}") from exc
            if response.get("id") != message_id:
                continue
            if "error" in response:
                raise CodexRuntimeError(f"MCP {method} failed: {response['error']}")
            result = response.get("result")
            return result if isinstance(result, dict) else {}

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    async def _send(self, message: dict[str, Any]) -> None:
        process = self._require_process()
        if process.stdin is None:
            raise CodexRuntimeError("MCP server stdin is not available")
        payload = json.dumps(message, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        if self.framing == "jsonl":
            process.stdin.write(payload + b"\n")
        elif self.framing == "content-length":
            process.stdin.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii") + payload)
        else:
            raise CodexRuntimeError(f"unsupported MCP framing mode: {self.framing}")
        await process.stdin.drain()

    async def _read(self) -> dict[str, Any]:
        if self.framing == "jsonl":
            return await self._read_jsonl()
        if self.framing == "content-length":
            return await self._read_content_length()
        raise CodexRuntimeError(f"unsupported MCP framing mode: {self.framing}")

    async def _read_jsonl(self) -> dict[str, Any]:
        process = self._require_process()
        if process.stdout is None:
            raise CodexRuntimeError("MCP server stdout is not available")
        line = await process.stdout.readline()
        if not line:
            stderr = await self._read_stderr()
            raise CodexRuntimeError(f"MCP server closed stdout{': ' + stderr if stderr else ''}")
        loaded = json.loads(line.decode("utf-8"))
        if not isinstance(loaded, dict):
            raise CodexRuntimeError("MCP line did not contain a JSON object")
        return loaded

    async def _read_content_length(self) -> dict[str, Any]:
        process = self._require_process()
        if process.stdout is None:
            raise CodexRuntimeError("MCP server stdout is not available")

        content_length: int | None = None
        while True:
            line = await process.stdout.readline()
            if not line:
                stderr = await self._read_stderr()
                raise CodexRuntimeError(f"MCP server closed stdout{': ' + stderr if stderr else ''}")
            stripped = line.strip()
            if not stripped:
                break
            key, _, value = stripped.decode("ascii", errors="replace").partition(":")
            if key.lower() == "content-length":
                content_length = int(value.strip())
        if content_length is None:
            raise CodexRuntimeError("MCP frame missing Content-Length header")
        raw = await process.stdout.readexactly(content_length)
        loaded = json.loads(raw.decode("utf-8"))
        if not isinstance(loaded, dict):
            raise CodexRuntimeError("MCP frame did not contain a JSON object")
        return loaded

    async def _read_stderr(self) -> str:
        process = self._process
        if process is None or process.stderr is None:
            return ""
        try:
            data = await asyncio.wait_for(process.stderr.read(4096), timeout=0.05)
        except asyncio.TimeoutError:
            return ""
        return data.decode("utf-8", errors="replace").strip()

    def _require_process(self) -> asyncio.subprocess.Process:
        if self._process is None:
            raise CodexRuntimeError("MCP server is not started")
        return self._process


def codex_mcp_command_from_environment() -> list[str]:
    configured = os.environ.get("CXW_CODEX_MCP_COMMAND")
    if configured:
        return shlex.split(configured)
    return [os.environ.get("CXW_CODEX_BIN", "codex"), "mcp-server"]
