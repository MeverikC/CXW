from __future__ import annotations

import asyncio

from cxw.daemon import DaemonServer
from cxw.events import EventBus
from cxw.ipc import request, start_server
from cxw.models import (
    AgentRecord,
    CommitRecord,
    EventRecord,
    EventType,
    ReviewDecision,
    ReviewRecord,
    Role,
    WorkspaceRecord,
)
from cxw.store import StateStore
from cxw.summaries import SummaryService
from cxw.workspace import WorkspaceLayout


def test_summary_service_generates_review_test_risk_and_merge_plan(tmp_path, monkeypatch):
    monkeypatch.setenv("CXW_HOME", str(tmp_path / "cxw-home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    layout = WorkspaceLayout.from_repo(repo)
    store = StateStore(layout)
    store.upsert_workspace(WorkspaceRecord(id=layout.workspace_id, repo_path=str(repo)))
    store.upsert_agent(
        AgentRecord(
            workspace_id=layout.workspace_id,
            name="backend-1",
            role=Role.BACKEND_CODER,
            branch="cxw/backend-1",
            worktree_path=str(repo),
        )
    )
    store.append_commit(
        CommitRecord(
            workspace_id=layout.workspace_id,
            agent="backend-1",
            branch="cxw/backend-1",
            sha="abc123",
            summary="backend work",
        )
    )
    store.append_review(
        ReviewRecord(
            workspace_id=layout.workspace_id,
            reviewer="reviewer-1",
            implementer="backend-1",
            branch="cxw/backend-1",
            decision=ReviewDecision.REQUEST_CHANGES,
            rationale="missing tests",
        )
    )
    store.append_event(
        EventRecord(
            workspace_id=layout.workspace_id,
            agent="tester-1",
            type=EventType.COMMAND,
            message="pytest failed",
            payload={"returncode": 1},
        )
    )

    service = SummaryService(store, EventBus(store, layout.workspace_id), layout.workspace_id)
    summaries = asyncio.run(service.generate())

    assert summaries["review_summary"]["request_changes"] == 1
    assert summaries["test_summary"]["failed_command_count"] == 1
    assert summaries["risk_summary"]["risk_count"] >= 1
    assert summaries["merge_plan"]["human_approval_required"] is True
    assert summaries["merge_plan"]["candidate_branches"][0]["latest_commit"] == "abc123"
    assert store.list_events(layout.workspace_id)[-1].type == "summary"


def test_daemon_generates_summaries(tmp_path, monkeypatch):
    monkeypatch.setenv("CXW_HOME", str(tmp_path / "cxw-home"))
    repo = tmp_path / "repo"
    repo.mkdir()

    async def run():
        daemon = DaemonServer(repo)
        await daemon.orchestrator.ensure_initialized()
        server, endpoint = await start_server(daemon.layout, daemon.handle)
        try:
            response = await request(endpoint, {"action": "summaries"})
            return response
        finally:
            server.close()
            await server.wait_closed()
            daemon.store.close()

    response = asyncio.run(run())

    assert response["ok"] is True
    assert response["summaries"]["merge_plan"]["autonomous_merge"] is False

