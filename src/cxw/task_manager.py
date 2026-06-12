"""Task management with dynamic adjustment and interruption support."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from cxw.events import EventBus
from cxw.models import AgentRecord, AgentStatus, EventType, TaskRecord, TaskStatus
from cxw.store import StateStore


class TaskPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class InterruptStrategy(str, Enum):
    WAIT_COMPLETION = "wait_completion"  # Let current task finish
    CANCEL_IMMEDIATE = "cancel_immediate"  # Stop now (not yet implemented)
    REPLACE_AFTER = "replace_after"  # Queue replacement task


@dataclass
class TaskAdjustment:
    """Record of task plan adjustment."""
    task_id: int
    reason: str
    old_description: str
    new_description: str
    strategy: InterruptStrategy
    timestamp: datetime


class TaskManager:
    """Enhanced task management with dynamic adjustment."""

    def __init__(self, store: StateStore, bus: EventBus, workspace_id: str):
        self.store = store
        self.bus = bus
        self.workspace_id = workspace_id
        self.adjustments: list[TaskAdjustment] = []

    async def create_task(
        self,
        title: str,
        description: str,
        assigned_agent: str,
        priority: TaskPriority = TaskPriority.NORMAL,
    ) -> TaskRecord:
        """Create a new task."""
        task = self.store.create_task(
            TaskRecord(
                workspace_id=self.workspace_id,
                title=title,
                description=description,
                assigned_agent=assigned_agent,
                status=TaskStatus.PENDING,
            )
        )

        await self.bus.publish(
            EventType.TASK_CREATED,
            agent="orchestrator",
            message=f"created task: {title}",
            payload={
                "task_id": task.id,
                "agent": assigned_agent,
                "priority": priority.value,
            },
        )

        return task

    async def adjust_task(
        self,
        task_id: int,
        new_description: str,
        reason: str,
        strategy: InterruptStrategy = InterruptStrategy.WAIT_COMPLETION,
    ) -> TaskRecord:
        """Adjust task requirements mid-execution."""
        task = self.store.get_task(task_id)
        if task is None:
            raise ValueError(f"task not found: {task_id}")

        adjustment = TaskAdjustment(
            task_id=task_id,
            reason=reason,
            old_description=task.description,
            new_description=new_description,
            strategy=strategy,
            timestamp=datetime.now(),
        )
        self.adjustments.append(adjustment)

        # Update task record
        self.store.update_task(
            task_id,
            description=new_description,
            status=TaskStatus.PENDING if strategy == InterruptStrategy.REPLACE_AFTER else task.status,
        )

        await self.bus.publish(
            EventType.ORCHESTRATOR_DECISION,
            agent="orchestrator",
            message=f"adjusted task {task_id}: {reason}",
            payload={
                "task_id": task_id,
                "agent": task.assigned_agent,
                "strategy": strategy.value,
                "reason": reason,
                "old_description": task.description,
                "new_description": new_description,
            },
        )

        # Handle interruption based on strategy
        if strategy == InterruptStrategy.WAIT_COMPLETION:
            await self.bus.publish(
                EventType.AGENT_MESSAGE,
                agent=task.assigned_agent,
                message=f"task will be adjusted after current work completes: {reason}",
                payload={"task_id": task_id},
            )
        elif strategy == InterruptStrategy.REPLACE_AFTER:
            agent = self.store.get_agent(self.workspace_id, task.assigned_agent)
            if agent and AgentStatus(agent.status) in (AgentStatus.RUNNING, AgentStatus.IDLE):
                await self.bus.publish(
                    EventType.TASK_ASSIGNED,
                    agent=task.assigned_agent,
                    message=f"replacement task queued: {new_description[:80]}",
                    payload={"task_id": task_id, "replaced": True},
                )

        return self.store.get_task(task_id) or task

    async def mark_blocked(self, task_id: int, reason: str) -> None:
        """Mark task as blocked."""
        self.store.update_task(task_id, status=TaskStatus.BLOCKED)
        await self.bus.publish(
            EventType.ORCHESTRATOR_DECISION,
            agent="orchestrator",
            message=f"task {task_id} blocked: {reason}",
            payload={"task_id": task_id, "reason": reason},
        )

    async def mark_done(self, task_id: int, summary: str = "") -> None:
        """Mark task as complete."""
        self.store.update_task(task_id, status=TaskStatus.DONE)
        await self.bus.publish(
            EventType.SUMMARY,
            agent="orchestrator",
            message=f"task {task_id} completed",
            payload={"task_id": task_id, "summary": summary},
        )

    def get_adjustments_for_task(self, task_id: int) -> list[TaskAdjustment]:
        """Get all adjustments for a task."""
        return [adj for adj in self.adjustments if adj.task_id == task_id]

    def get_pending_tasks(self, agent: str | None = None) -> list[TaskRecord]:
        """Get pending tasks, optionally filtered by agent."""
        tasks = self.store.list_tasks(self.workspace_id)
        pending = [t for t in tasks if TaskStatus(t.status) == TaskStatus.PENDING]
        if agent:
            pending = [t for t in pending if t.assigned_agent == agent]
        return pending

    def get_active_tasks(self) -> list[TaskRecord]:
        """Get all active (running/assigned) tasks."""
        tasks = self.store.list_tasks(self.workspace_id)
        return [
            t for t in tasks
            if TaskStatus(t.status) in (TaskStatus.ASSIGNED, TaskStatus.RUNNING)
        ]
