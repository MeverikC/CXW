from __future__ import annotations

from cxw.events import EventBus
from cxw.models import EventType, ReviewDecision, ReviewRecord
from cxw.store import StateStore


class ReviewService:
    def __init__(self, store: StateStore, bus: EventBus, workspace_id: str):
        self.store = store
        self.bus = bus
        self.workspace_id = workspace_id

    async def record_review(
        self,
        *,
        reviewer: str,
        implementer: str,
        branch: str,
        decision: ReviewDecision,
        rationale: str,
    ) -> ReviewRecord:
        review = self.store.append_review(
            ReviewRecord(
                workspace_id=self.workspace_id,
                reviewer=reviewer,
                implementer=implementer,
                branch=branch,
                decision=decision,
                rationale=rationale,
            )
        )
        await self.bus.publish(
            EventType.REVIEW,
            agent=reviewer,
            message=f"{decision.value}: {branch}",
            payload=review.model_dump(mode="json"),
        )
        return review

