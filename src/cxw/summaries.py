from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from cxw.events import EventBus
from cxw.models import AgentStatus, EventType, ReviewDecision, Role
from cxw.serialization import to_jsonable
from cxw.store import StateStore


IMPLEMENTER_ROLES = {Role.FRONTEND_CODER.value, Role.BACKEND_CODER.value}


@dataclass
class SummaryService:
    store: StateStore
    bus: EventBus
    workspace_id: str

    async def generate(self) -> dict[str, Any]:
        bundle = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "review_summary": self.review_summary(),
            "test_summary": self.test_summary(),
            "risk_summary": self.risk_summary(),
            "merge_plan": self.merge_plan(),
        }
        await self.bus.publish(
            EventType.SUMMARY,
            agent="orchestrator",
            message="generated review, test, risk, and merge summaries",
            payload=to_jsonable(bundle),
        )
        return to_jsonable(bundle)

    def review_summary(self) -> dict[str, Any]:
        reviews = self.store.list_reviews(self.workspace_id)
        approvals = [review for review in reviews if review.decision == ReviewDecision.APPROVE.value]
        changes = [
            review for review in reviews if review.decision == ReviewDecision.REQUEST_CHANGES.value
        ]
        latest_by_branch: dict[str, str] = {}
        for review in reviews:
            latest_by_branch[review.branch] = review.decision
        return {
            "total_reviews": len(reviews),
            "approved": len(approvals),
            "request_changes": len(changes),
            "latest_decision_by_branch": latest_by_branch,
            "human_approval_required": True,
        }

    def test_summary(self) -> dict[str, Any]:
        events = self.store.list_events(self.workspace_id)
        command_events = [event for event in events if event.type == EventType.COMMAND.value]
        failed_commands = [
            event
            for event in command_events
            if int((event.payload or {}).get("returncode") or 0) != 0
        ]
        tester_events = [event for event in events if event.agent == "tester-1"]
        return {
            "command_count": len(command_events),
            "failed_command_count": len(failed_commands),
            "tester_event_count": len(tester_events),
            "latest_failed_commands": [
                {
                    "agent": event.agent,
                    "message": event.message,
                    "returncode": (event.payload or {}).get("returncode"),
                }
                for event in failed_commands[-5:]
            ],
        }

    def risk_summary(self) -> dict[str, Any]:
        agents = self.store.list_agents(self.workspace_id)
        reviews = self.store.list_reviews(self.workspace_id)
        events = self.store.list_events(self.workspace_id)
        notes: list[str] = []

        failed_agents = [
            agent.name
            for agent in agents
            if agent.status in {AgentStatus.FAILED.value, AgentStatus.STOPPED.value}
        ]
        if failed_agents:
            notes.append(f"Agents not running normally: {', '.join(failed_agents)}")

        request_changes = [
            review.branch
            for review in reviews
            if review.decision == ReviewDecision.REQUEST_CHANGES.value
        ]
        if request_changes:
            notes.append(f"Branches with requested changes: {', '.join(sorted(set(request_changes)))}")

        failed_events = [event for event in events if event.type == EventType.FAILED.value]
        if failed_events:
            notes.append(f"Failure events recorded: {len(failed_events)}")

        failed_commands = [
            event
            for event in events
            if event.type == EventType.COMMAND.value
            and int((event.payload or {}).get("returncode") or 0) != 0
        ]
        if failed_commands:
            notes.append(f"Failed commands recorded: {len(failed_commands)}")

        if not notes:
            notes.append("No persisted risk signals detected.")

        return {"risk_notes": notes, "risk_count": len(notes)}

    def merge_plan(self) -> dict[str, Any]:
        agents = self.store.list_agents(self.workspace_id)
        commits = self.store.list_commits(self.workspace_id)
        branches: dict[str, dict[str, Any]] = {}
        for agent in agents:
            if agent.role in IMPLEMENTER_ROLES and agent.branch:
                branches[agent.branch] = {
                    "agent": agent.name,
                    "branch": agent.branch,
                    "worktree_path": agent.worktree_path,
                    "latest_commit": None,
                }
        for commit in commits:
            if commit.branch in branches:
                branches[commit.branch]["latest_commit"] = commit.sha

        branch_list = list(branches.values())
        steps = [
            "Review each implementation branch summary and review decision.",
            "Run or inspect tester verification output.",
            "Inspect diffs against the base branch.",
            "Ask the human approver for final approval.",
            "After approval, merge branches manually in the target repository.",
        ]
        return {
            "candidate_branches": branch_list,
            "branch_count": len(branch_list),
            "human_approval_required": True,
            "autonomous_merge": False,
            "steps": steps,
        }

