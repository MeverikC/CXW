from __future__ import annotations

from rich.console import Console

from cxw.ui import render_workspaces


def test_render_workspaces_empty_state_is_visible():
    console = Console(record=True, width=120)

    render_workspaces(console, [])

    assert "No CXW workspaces found" in console.export_text()

