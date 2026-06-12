from __future__ import annotations

from cxw.tui import (
    _conversation_events,
    _event_message,
    _is_plan_command,
    _is_run_command,
    _main_agent_name,
    _plan_command_args,
    _run_payload,
)


def test_main_agent_name_prefers_project_config():
    assert (
        _main_agent_name(
            {
                "project_config": {"main_agent": {"name": "lead-1"}},
                "agents": [{"name": "main-1", "role": "orchestrator"}],
            }
        )
        == "lead-1"
    )


def test_main_agent_name_falls_back_to_orchestrator_agent():
    assert (
        _main_agent_name(
            {
                "project_config": {},
                "agents": [{"name": "main-2", "role": "orchestrator"}],
            }
        )
        == "main-2"
    )


def test_conversation_events_filters_user_and_agent_messages():
    events = _conversation_events(
        {
            "recent_events": [
                {"type": "summary", "message": "noise"},
                {"type": "user_message", "message": "hello"},
                {"type": "agent_message", "message": "hi"},
            ]
        }
    )

    assert [event["message"] for event in events] == ["hello", "hi"]
    assert _event_message(events[1]) == "hi"


def test_plan_command_detection_and_args():
    assert _is_plan_command("/plan") is True
    assert _is_plan_command("/plan auto build app") is True
    assert _is_plan_command("/planet") is False
    assert _plan_command_args("/plan auto build app") == "auto build app"


def test_run_command_detection_and_payload():
    assert _is_run_command("/run") is True
    assert _is_run_command("/run --runtime codex-mcp") is True
    assert _is_run_command("/runner") is False
    assert _run_payload("/run") == {"action": "run_plan"}
    assert _run_payload("/run --runtime local-deterministic") == {
        "action": "run_plan",
        "runtime": "local-deterministic",
    }
