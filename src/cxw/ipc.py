from __future__ import annotations

import asyncio
import json
import os
import socket
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable

from cxw.errors import DaemonError, ProtocolError
from cxw.serialization import dumps_json
from cxw.workspace import WorkspaceLayout

JsonHandler = Callable[[dict[str, Any], asyncio.StreamWriter], Awaitable[None]]
MAX_UNIX_SOCKET_PATH_BYTES = 103


class TransportKind(str, Enum):
    UNIX = "unix"
    TCP = "tcp"


@dataclass(frozen=True)
class Endpoint:
    kind: TransportKind
    path: str | None = None
    host: str = "127.0.0.1"
    port: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "path": self.path,
            "host": self.host,
            "port": self.port,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Endpoint":
        return cls(
            kind=TransportKind(value["kind"]),
            path=value.get("path"),
            host=value.get("host") or "127.0.0.1",
            port=value.get("port"),
        )


def endpoint_from_layout(layout: WorkspaceLayout) -> Endpoint:
    if os.name != "nt" and hasattr(asyncio, "start_unix_server") and hasattr(socket, "AF_UNIX"):
        socket_path = str(layout.run_dir / "cxw.sock")
        if len(os.fsencode(socket_path)) <= MAX_UNIX_SOCKET_PATH_BYTES:
            return Endpoint(kind=TransportKind.UNIX, path=socket_path)
    return Endpoint(kind=TransportKind.TCP, host="127.0.0.1", port=None)


def write_endpoint(layout: WorkspaceLayout, endpoint: Endpoint) -> None:
    layout.ensure()
    layout.require_internal_path(layout.endpoint_path)
    layout.endpoint_path.write_text(dumps_json(endpoint.to_dict()), encoding="utf-8")


def read_endpoint(layout: WorkspaceLayout) -> Endpoint | None:
    if not layout.endpoint_path.exists():
        return None
    try:
        raw = json.loads(layout.endpoint_path.read_text(encoding="utf-8"))
        return Endpoint.from_dict(raw)
    except (OSError, ValueError, KeyError, TypeError):
        return None


async def open_connection(endpoint: Endpoint) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    if endpoint.kind == TransportKind.UNIX:
        if not endpoint.path:
            raise DaemonError("unix endpoint missing socket path")
        return await asyncio.open_unix_connection(endpoint.path)
    if endpoint.port is None:
        raise DaemonError("tcp endpoint missing port")
    return await asyncio.open_connection(endpoint.host, endpoint.port)


async def send_json(writer: asyncio.StreamWriter, value: dict[str, Any]) -> None:
    writer.write(dumps_json(value).encode("utf-8") + b"\n")
    await writer.drain()


async def read_json_line(reader: asyncio.StreamReader) -> dict[str, Any] | None:
    line = await reader.readline()
    if not line:
        return None
    try:
        value = json.loads(line.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"invalid JSON from daemon: {exc}") from exc
    if not isinstance(value, dict):
        raise ProtocolError("daemon response must be a JSON object")
    return value


async def request(endpoint: Endpoint, payload: dict[str, Any]) -> dict[str, Any]:
    reader, writer = await open_connection(endpoint)
    try:
        await send_json(writer, payload)
        response = await read_json_line(reader)
        if response is None:
            raise DaemonError("daemon closed connection without a response")
        if response.get("ok") is False:
            raise DaemonError(str(response.get("error") or "daemon request failed"))
        return response
    finally:
        writer.close()
        await writer.wait_closed()


async def stream_request(
    endpoint: Endpoint, payload: dict[str, Any]
) -> AsyncIterator[dict[str, Any]]:
    reader, writer = await open_connection(endpoint)
    try:
        await send_json(writer, payload)
        while True:
            item = await read_json_line(reader)
            if item is None:
                return
            if item.get("ok") is False:
                raise DaemonError(str(item.get("error") or "daemon stream failed"))
            yield item
    finally:
        writer.close()
        await writer.wait_closed()


async def ping(endpoint: Endpoint) -> bool:
    try:
        response = await asyncio.wait_for(request(endpoint, {"action": "ping"}), timeout=1.0)
    except Exception:
        return False
    return bool(response.get("ok"))


async def start_server(
    layout: WorkspaceLayout, handler: JsonHandler
) -> tuple[asyncio.AbstractServer, Endpoint]:
    endpoint = endpoint_from_layout(layout)

    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            payload = await read_json_line(reader)
            if payload is None:
                return
            await handler(payload, writer)
        except Exception as exc:
            await send_json(writer, {"ok": False, "error": str(exc)})
        finally:
            writer.close()
            await writer.wait_closed()

    if endpoint.kind == TransportKind.UNIX:
        socket_path = Path(endpoint.path or "")
        if socket_path.exists():
            # This is limited to CXW's generated run directory and is required before binding.
            socket_path.unlink()
        server = await asyncio.start_unix_server(handle_client, path=endpoint.path)
    else:
        server = await asyncio.start_server(handle_client, endpoint.host, 0)
        sockets = server.sockets or []
        if not sockets:
            raise DaemonError("tcp daemon did not expose a listening socket")
        endpoint = Endpoint(
            kind=TransportKind.TCP,
            host=endpoint.host,
            port=int(sockets[0].getsockname()[1]),
        )
    write_endpoint(layout, endpoint)
    return server, endpoint
