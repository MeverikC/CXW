"""Enhanced TUI with real-time multi-agent progress tracking."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskID
from rich.table import Table
from rich.text import Text

from cxw.daemon import daemon_request
from cxw.ipc import read_endpoint
from cxw.workspace import WorkspaceLayout


@dataclass
class AgentProgress:
    """Track progress for a single agent."""
    name: str
    status: str
    current_task: str
    progress_bar: TaskID | None = None
    last_update: datetime = None


class MultiAgentProgressTUI:
    """Real-time TUI showing all agent progress simultaneously."""

    def __init__(self, repo: Path, console: Console | None = None):
        self.repo = repo
        self.console = console or Console()
        self.agents: dict[str, AgentProgress] = {}
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold]{task.description}"),
            BarColumn(),
            TextColumn("{task.fields[status]}"),
            console=self.console,
        )
        self.event_log: list[tuple[datetime, str, str]] = []
        self.max_log_lines = 20

    async def run_with_monitoring(self) -> None:
        """Run with live progress monitoring."""
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="agents", size=15),
            Layout(name="events", size=15),
            Layout(name="footer", size=3),
        )

        with Live(layout, console=self.console, refresh_per_second=4) as live:
            self._update_layout(layout)

            # Start event stream monitoring in background
            monitor_task = asyncio.create_task(self._monitor_events())

            try:
                # Wait for completion or user interrupt
                await asyncio.sleep(3600)  # 1 hour max
            except asyncio.CancelledError:
                pass
            finally:
                monitor_task.cancel()
                try:
                    await monitor_task
                except asyncio.CancelledError:
                    pass

    async def _monitor_events(self) -> None:
        """Monitor daemon event stream and update progress."""
        try:
            layout = WorkspaceLayout.from_repo(self.repo)
            endpoint = read_endpoint(layout)
            if not endpoint:
                return

            # Connect to event stream
            reader, writer = await asyncio.open_connection(endpoint.host, endpoint.port)

            # Send stream request
            import json
            request = json.dumps({"action": "stream_events", "follow": True}) + "\n"
            writer.write(request.encode("utf-8"))
            await writer.drain()

            # Read events
            while True:
                line = await reader.readline()
                if not line:
                    break

                data = json.loads(line.decode("utf-8"))
                if data.get("ok") and "event" in data:
                    event = data["event"]
                    self._process_event(event)

        except Exception as e:
            self._add_event("system", f"Monitor error: {e}")

    def _process_event(self, event: dict[str, Any]) -> None:
        """Process incoming event and update UI."""
        agent = event.get("agent", "system")
        event_type = event.get("type", "")
        message = event.get("message", "")

        self._add_event(agent, message)

        # Update agent progress based on event type
        if event_type in ("task_assigned", "agent_created"):
            if agent not in self.agents:
                self.agents[agent] = AgentProgress(
                    name=agent,
                    status="assigned",
                    current_task=message,
                    last_update=datetime.now(),
                )
        elif event_type in ("tool_call", "command", "write_file"):
            if agent in self.agents:
                self.agents[agent].status = "active"
                self.agents[agent].current_task = message
                self.agents[agent].last_update = datetime.now()
        elif event_type == "summary":
            if agent in self.agents:
                self.agents[agent].status = "completed"
                self.agents[agent].last_update = datetime.now()
        elif event_type == "failed":
            if agent in self.agents:
                self.agents[agent].status = "failed"
                self.agents[agent].last_update = datetime.now()

    def _add_event(self, agent: str, message: str) -> None:
        """Add event to log."""
        self.event_log.append((datetime.now(), agent, message))
        if len(self.event_log) > self.max_log_lines:
            self.event_log.pop(0)

    def _update_layout(self, layout: Layout) -> None:
        """Update all layout sections."""
        layout["header"].update(Panel(
            Text("CXW Multi-Agent Orchestration", justify="center", style="bold cyan"),
            style="blue",
        ))

        layout["agents"].update(self._render_agents_panel())
        layout["events"].update(self._render_events_panel())
        layout["footer"].update(Panel(
            Text("Press Ctrl+C to stop monitoring", justify="center", style="dim"),
        ))

    def _render_agents_panel(self) -> Panel:
        """Render agent progress table."""
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Agent", style="cyan", width=20)
        table.add_column("Status", width=12)
        table.add_column("Current Task", overflow="fold")

        status_styles = {
            "idle": "dim",
            "assigned": "yellow",
            "running": "green",
            "active": "bold green",
            "completed": "blue",
            "failed": "red",
        }

        for agent in self.agents.values():
            style = status_styles.get(agent.status, "")
            table.add_row(
                agent.name,
                Text(agent.status, style=style),
                agent.current_task[:60] + "..." if len(agent.current_task) > 60 else agent.current_task,
            )

        if not self.agents:
            table.add_row("—", Text("No active agents", style="dim"), "—")

        return Panel(table, title="[bold]Agent Status", border_style="blue")

    def _render_events_panel(self) -> Panel:
        """Render recent events log."""
        if not self.event_log:
            return Panel(Text("No events yet", style="dim"), title="[bold]Event Log", border_style="green")

        lines = []
        for ts, agent, msg in self.event_log[-self.max_log_lines:]:
            time_str = ts.strftime("%H:%M:%S")
            lines.append(f"[dim]{time_str}[/dim] [cyan]{agent:12}[/cyan] {msg}")

        return Panel(
            "\n".join(lines),
            title="[bold]Event Log",
            border_style="green",
        )


async def run_interactive_tui(repo: Path) -> None:
    """Run enhanced interactive TUI with progress monitoring."""
    console = Console()
    tui = MultiAgentProgressTUI(repo, console)

    try:
        await tui.run_with_monitoring()
    except KeyboardInterrupt:
        console.print("\n[yellow]Monitoring stopped by user[/yellow]")
