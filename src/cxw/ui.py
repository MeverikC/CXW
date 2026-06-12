from __future__ import annotations

from datetime import datetime
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from cxw.registry import WorkspaceSummary


def _short(value: str | None, limit: int = 80) -> str:
    if not value:
        return ""
    return value if len(value) <= limit else value[: limit - 1] + "..."


def _time(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.strftime("%H:%M:%S")
    except ValueError:
        return value


def render_status(console: Console, snapshot: dict[str, Any]) -> None:
    workspace = snapshot.get("workspace") or {}
    paths = snapshot.get("paths") or {}
    agents = snapshot.get("agents") or []
    tasks = snapshot.get("tasks") or []
    events = snapshot.get("recent_events") or []
    transitions = snapshot.get("state_transitions") or []
    project_config = snapshot.get("project_config") or {}

    workspace_text = Text()
    workspace_text.append("Repository: ", style="bold")
    workspace_text.append(str(paths.get("repo") or workspace.get("repo_path") or ""))
    workspace_text.append("\nWorkspace: ", style="bold")
    workspace_text.append(str(paths.get("workspace") or ""))
    workspace_text.append("\nState: ", style="bold")
    workspace_text.append(str(workspace.get("state") or "unknown"), style="cyan")
    console.print(Panel(workspace_text, title="Workspace", expand=True))

    if project_config:
        config_text = Text()
        config_text.append("Path: ", style="bold")
        config_text.append(str(project_config.get("path") or ""))
        config_text.append("\nStatus: ", style="bold")
        if project_config.get("valid"):
            config_text.append("valid", style="green")
            workspace_config = project_config.get("workspace") or {}
            config_text.append("\nPlan: ", style="bold")
            config_text.append(str(workspace_config.get("name") or ""))
            config_text.append("\nGoal: ", style="bold")
            config_text.append(_short(str(workspace_config.get("goal") or ""), 140))
        else:
            if project_config.get("created_template"):
                config_text.append("template created", style="yellow")
            elif project_config.get("exists"):
                config_text.append("invalid", style="red")
            else:
                config_text.append("missing", style="red")
            errors = project_config.get("errors") or []
            if errors:
                config_text.append("\nRequired action: ", style="bold")
                config_text.append(_short(str(errors[0]), 160))
        console.print(Panel(config_text, title="Project Config", expand=True))

    plan = Table(title="Plan", expand=True)
    plan.add_column("ID", width=6)
    plan.add_column("Status", width=12)
    plan.add_column("Agent", width=14)
    plan.add_column("Task")
    if tasks:
        for task in tasks:
            plan.add_row(
                str(task.get("id") or ""),
                str(task.get("status") or ""),
                str(task.get("assigned_agent") or ""),
                str(task.get("title") or ""),
            )
    else:
        plan.add_row("", "pending", "planner-1", "No plan has been approved yet")
    console.print(plan)

    table = Table(title="Agent Status", expand=True)
    table.add_column("Agent", width=14)
    table.add_column("Role", width=16)
    table.add_column("Status", width=12)
    table.add_column("Goal")
    table.add_column("Action")
    table.add_column("Next")
    for agent in agents:
        table.add_row(
            str(agent.get("name") or ""),
            str(agent.get("role") or ""),
            str(agent.get("status") or ""),
            _short(agent.get("current_goal")),
            _short(agent.get("current_action")),
            _short(agent.get("next_action")),
        )
    console.print(table)

    event_table = Table(title="Recent Events", expand=True)
    event_table.add_column("Seq", width=6)
    event_table.add_column("Time", width=10)
    event_table.add_column("Agent", width=14)
    event_table.add_column("Type", width=22)
    event_table.add_column("Message")
    for event in events[-10:]:
        event_table.add_row(
            str(event.get("sequence") or ""),
            _time(event.get("ts")),
            str(event.get("agent") or ""),
            str(event.get("type") or ""),
            _short(event.get("message"), 100),
        )
    console.print(event_table)

    decisions = Table(title="Orchestrator Decisions", expand=True)
    decisions.add_column("Time", width=10)
    decisions.add_column("From", width=24)
    decisions.add_column("To", width=24)
    decisions.add_column("Reason")
    for transition in transitions[-8:]:
        decisions.add_row(
            _time(transition.get("ts")),
            str(transition.get("from_state") or ""),
            str(transition.get("to_state") or ""),
            _short(transition.get("reason"), 100),
        )
    console.print(decisions)


def format_event_line(event: dict[str, Any]) -> str:
    ts = _time(event.get("ts"))
    agent = event.get("agent") or "workspace"
    event_type = event.get("type") or ""
    message = event.get("message") or ""
    return f"[{ts}] {agent} {event_type}: {message}".rstrip()


def render_workspaces(console: Console, summaries: list[WorkspaceSummary]) -> None:
    table = Table(title="Known Workspaces", expand=True)
    table.add_column("Workspace ID", width=14)
    table.add_column("State", width=22)
    table.add_column("Daemon", width=10)
    table.add_column("Agents", justify="right", width=8)
    table.add_column("Events", justify="right", width=8)
    table.add_column("Repository")
    if not summaries:
        table.add_row("No workspaces", "-", "-", "0", "0", "No CXW workspaces found")
    for summary in summaries:
        table.add_row(
            summary.workspace_id[:12],
            summary.state or "unknown",
            "running" if summary.daemon_running else "stopped",
            str(summary.agent_count),
            str(summary.event_count),
            summary.repo_path or "",
        )
    console.print(table)


def render_health(console: Console, health: dict[str, Any]) -> None:
    counts = health.get("counts") or {}
    paths = health.get("paths") or {}
    text = Text()
    text.append("PID: ", style="bold")
    text.append(str(health.get("pid") or "unknown"))
    text.append("\nWorkspace: ", style="bold")
    text.append(str(health.get("workspace_id") or ""))
    text.append("\nRepository: ", style="bold")
    text.append(str(health.get("repo_path") or ""))
    text.append("\nState: ", style="bold")
    text.append(str(health.get("state") or "unknown"), style="cyan")
    text.append("\nEvents: ", style="bold")
    text.append(str(counts.get("events") or 0))
    text.append("\nAgents: ", style="bold")
    text.append(str(counts.get("agents") or 0))
    text.append("\nDatabase: ", style="bold")
    text.append(str(paths.get("db") or ""))
    console.print(Panel(text, title="Daemon Health", expand=True))


def render_workspace_info(console: Console, info: dict[str, Any]) -> None:
    health = info.get("health") or {}
    render_health(console, health)
    snapshot = info.get("snapshot")
    if isinstance(snapshot, dict):
        render_status(console, snapshot)


def render_summaries(console: Console, summaries: dict[str, Any]) -> None:
    review = summaries.get("review_summary") or {}
    tests = summaries.get("test_summary") or {}
    risk = summaries.get("risk_summary") or {}
    merge = summaries.get("merge_plan") or {}

    review_text = Text()
    review_text.append("Reviews: ", style="bold")
    review_text.append(str(review.get("total_reviews", 0)))
    review_text.append("\nApproved: ", style="bold")
    review_text.append(str(review.get("approved", 0)))
    review_text.append("\nRequest changes: ", style="bold")
    review_text.append(str(review.get("request_changes", 0)))
    review_text.append("\nHuman approval required: ", style="bold")
    review_text.append(str(review.get("human_approval_required", True)))
    console.print(Panel(review_text, title="Review Summary", expand=True))

    test_text = Text()
    test_text.append("Commands: ", style="bold")
    test_text.append(str(tests.get("command_count", 0)))
    test_text.append("\nFailed commands: ", style="bold")
    test_text.append(str(tests.get("failed_command_count", 0)))
    test_text.append("\nTester events: ", style="bold")
    test_text.append(str(tests.get("tester_event_count", 0)))
    console.print(Panel(test_text, title="Test Summary", expand=True))

    risk_table = Table(title="Risk Summary", expand=True)
    risk_table.add_column("Note")
    for note in risk.get("risk_notes") or []:
        risk_table.add_row(str(note))
    console.print(risk_table)

    merge_table = Table(title="Merge Plan", expand=True)
    merge_table.add_column("Branch")
    merge_table.add_column("Agent")
    merge_table.add_column("Latest Commit")
    for branch in merge.get("candidate_branches") or []:
        merge_table.add_row(
            str(branch.get("branch") or ""),
            str(branch.get("agent") or ""),
            str(branch.get("latest_commit") or ""),
        )
    if not merge.get("candidate_branches"):
        merge_table.add_row("", "", "No implementation branches recorded")
    console.print(merge_table)

    step_table = Table(title="Merge Steps", expand=True)
    step_table.add_column("Step")
    for step in merge.get("steps") or []:
        step_table.add_row(str(step))
    console.print(step_table)
