from __future__ import annotations

import asyncio

from pathlib import Path

from cxw import cli
from cxw.cli import (
    _extract_interactive_mode,
    _extract_json_flag,
    _extract_runtime_option,
    _should_run_interactive,
)


def test_extract_json_flag_accepts_any_position():
    enabled, args = _extract_json_flag(["--json", "/repo", "status", "--json"])

    assert enabled is True
    assert args == ["/repo", "status"]


def test_extract_interactive_mode_accepts_force_flag_any_position():
    mode, args = _extract_interactive_mode(["--interactive", "/repo", "-i"])

    assert mode == "force"
    assert args == ["/repo"]


def test_extract_interactive_mode_accepts_disable_flag():
    mode, args = _extract_interactive_mode(["/repo", "--no-interactive"])

    assert mode == "off"
    assert args == ["/repo"]


def test_should_run_interactive_respects_forced_modes():
    assert _should_run_interactive("force") is True
    assert _should_run_interactive("off") is False


def test_extract_runtime_option_accepts_space_and_equals_forms():
    assert _extract_runtime_option(["--runtime", "codex-mcp"]) == ("codex-mcp", [])
    assert _extract_runtime_option(["--runtime=local-deterministic"]) == (
        "local-deterministic",
        [],
    )
    assert _extract_runtime_option(["extra"]) == (None, ["extra"])


def test_dispatch_plan_command_calls_daemon(monkeypatch):
    calls = []

    async def fake_daemon_request(repo, payload):
        calls.append((repo, payload))
        return {"ok": True, "reply": "plan status", "snapshot": {}}

    monkeypatch.setattr(cli, "daemon_request", fake_daemon_request)

    asyncio.run(cli._dispatch(["/repo", "plan", "status"]))

    assert calls == [(Path("/repo"), {"action": "plan_command", "command": "status"})]


def test_dispatch_run_command_calls_daemon(monkeypatch):
    calls = []

    async def fake_daemon_request(repo, payload):
        calls.append((repo, payload))
        return {"ok": True, "reply": "running", "snapshot": {}}

    monkeypatch.setattr(cli, "daemon_request", fake_daemon_request)
    monkeypatch.setattr(cli, "render_status", lambda console, snapshot: None)

    asyncio.run(cli._dispatch(["/repo", "run", "--runtime", "local-deterministic"]))

    assert calls == [
        (Path("/repo"), {"action": "run_plan", "runtime": "local-deterministic"})
    ]
