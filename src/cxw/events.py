from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import AsyncIterator

from cxw.models import EventRecord, EventType
from cxw.store import StateStore


@dataclass(frozen=True)
class _Subscriber:
    agent: str | None
    queue: asyncio.Queue[EventRecord]


class EventBus:
    """Persisted event stream with in-process realtime subscribers."""

    def __init__(self, store: StateStore, workspace_id: str):
        self.store = store
        self.workspace_id = workspace_id
        self._subscribers: set[_Subscriber] = set()

    async def publish(
        self,
        event_type: EventType | str,
        *,
        agent: str | None = None,
        message: str = "",
        payload: dict | None = None,
    ) -> EventRecord:
        record = self.store.append_event(
            EventRecord(
                workspace_id=self.workspace_id,
                agent=agent,
                type=event_type,
                message=message,
                payload=payload or {},
            )
        )
        for subscriber in list(self._subscribers):
            if subscriber.agent is None or subscriber.agent == record.agent:
                subscriber.queue.put_nowait(record)
        return record

    async def stream(
        self,
        *,
        agent: str | None = None,
        after_sequence: int = 0,
        follow: bool = True,
    ) -> AsyncIterator[EventRecord]:
        latest_sequence = after_sequence
        for event in self.store.list_events(
            self.workspace_id, agent=agent, after_sequence=after_sequence
        ):
            latest_sequence = event.sequence or latest_sequence
            yield event
        if not follow:
            return

        queue: asyncio.Queue[EventRecord] = asyncio.Queue()
        subscriber = _Subscriber(agent=agent, queue=queue)
        self._subscribers.add(subscriber)
        try:
            while True:
                event = await queue.get()
                if (event.sequence or 0) > latest_sequence:
                    latest_sequence = event.sequence or latest_sequence
                    yield event
        finally:
            self._subscribers.discard(subscriber)

