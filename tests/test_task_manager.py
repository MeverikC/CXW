"""Tests for task manager with dynamic adjustment."""
import pytest

from cxw.events import EventBus
from cxw.models import AgentRecord, AgentStatus, Role, TaskStatus
from cxw.store import StateStore
from cxw.task_manager import InterruptStrategy, TaskManager, TaskPriority
from cxw.workspace import WorkspaceLayout


@pytest.fixture
def workspace_layout(tmp_path):
    """Create test workspace layout."""
    repo = tmp_path / "test-repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    layout = WorkspaceLayout.from_repo(repo)
    layout.ensure()
    return layout


@pytest.fixture
def store(workspace_layout):
    """Create test store."""
    return StateStore(workspace_layout)


@pytest.fixture
def bus(store, workspace_layout):
    """Create test event bus."""
    return EventBus(store, workspace_layout.workspace_id)


@pytest.fixture
def task_manager(store, bus, workspace_layout):
    """Create task manager instance."""
    # Ensure workspace exists
    from cxw.models import WorkspaceRecord
    store.upsert_workspace(WorkspaceRecord(
        id=workspace_layout.workspace_id,
        repo_path=str(workspace_layout.repo_path),
    ))
    return TaskManager(store, bus, workspace_layout.workspace_id)


@pytest.mark.asyncio
async def test_create_task(task_manager: TaskManager, store: StateStore):
    """Test task creation."""
    workspace_id = task_manager.workspace_id

    store.upsert_agent(
        AgentRecord(
            workspace_id=workspace_id,
            name="worker-1",
            role=Role.BACKEND_CODER,
            status=AgentStatus.IDLE,
        )
    )

    task = await task_manager.create_task(
        title="Build API",
        description="Create REST API",
        assigned_agent="worker-1",
        priority=TaskPriority.HIGH,
    )

    assert task.id is not None
    assert task.title == "Build API"
    assert task.description == "Create REST API"
    assert task.assigned_agent == "worker-1"
    assert TaskStatus(task.status) == TaskStatus.PENDING

    # Verify task is in store
    stored_task = store.get_task(task.id)
    assert stored_task is not None
    assert stored_task.title == "Build API"


@pytest.mark.asyncio
async def test_adjust_task(task_manager: TaskManager, store: StateStore):
    """Test task adjustment."""
    workspace_id = task_manager.workspace_id

    store.upsert_agent(
        AgentRecord(
            workspace_id=workspace_id,
            name="worker-1",
            role=Role.BACKEND_CODER,
            status=AgentStatus.IDLE,
        )
    )

    task = await task_manager.create_task(
        title="Build API",
        description="Create REST API with Flask",
        assigned_agent="worker-1",
    )

    # Adjust the task
    adjusted = await task_manager.adjust_task(
        task.id,
        new_description="Create REST API with FastAPI instead",
        reason="FastAPI has better async support",
        strategy=InterruptStrategy.WAIT_COMPLETION,
    )

    assert adjusted.description == "Create REST API with FastAPI instead"

    # Check adjustment was recorded
    adjustments = task_manager.get_adjustments_for_task(task.id)
    assert len(adjustments) == 1
    assert adjustments[0].reason == "FastAPI has better async support"
    assert adjustments[0].old_description == "Create REST API with Flask"
    assert adjustments[0].new_description == "Create REST API with FastAPI instead"
    assert adjustments[0].strategy == InterruptStrategy.WAIT_COMPLETION


@pytest.mark.asyncio
async def test_adjust_task_with_replace_strategy(task_manager: TaskManager, store: StateStore):
    """Test task adjustment with replace strategy."""
    workspace_id = task_manager.workspace_id

    store.upsert_agent(
        AgentRecord(
            workspace_id=workspace_id,
            name="worker-1",
            role=Role.BACKEND_CODER,
            status=AgentStatus.IDLE,
        )
    )

    task = await task_manager.create_task(
        title="Build feature",
        description="Original description",
        assigned_agent="worker-1",
    )

    adjusted = await task_manager.adjust_task(
        task.id,
        new_description="Completely different feature",
        reason="Requirements changed",
        strategy=InterruptStrategy.REPLACE_AFTER,
    )

    # Task should be set back to pending
    assert TaskStatus(adjusted.status) == TaskStatus.PENDING
    assert adjusted.description == "Completely different feature"


@pytest.mark.asyncio
async def test_mark_blocked(task_manager: TaskManager, store: StateStore):
    """Test marking task as blocked."""
    workspace_id = task_manager.workspace_id

    store.upsert_agent(
        AgentRecord(
            workspace_id=workspace_id,
            name="worker-1",
            role=Role.BACKEND_CODER,
            status=AgentStatus.IDLE,
        )
    )

    task = await task_manager.create_task(
        title="Build feature",
        description="Feature desc",
        assigned_agent="worker-1",
    )

    await task_manager.mark_blocked(task.id, "Waiting for API spec")

    updated = store.get_task(task.id)
    assert TaskStatus(updated.status) == TaskStatus.BLOCKED


@pytest.mark.asyncio
async def test_mark_done(task_manager: TaskManager, store: StateStore):
    """Test marking task as done."""
    workspace_id = task_manager.workspace_id

    store.upsert_agent(
        AgentRecord(
            workspace_id=workspace_id,
            name="worker-1",
            role=Role.BACKEND_CODER,
            status=AgentStatus.IDLE,
        )
    )

    task = await task_manager.create_task(
        title="Build feature",
        description="Feature desc",
        assigned_agent="worker-1",
    )

    await task_manager.mark_done(task.id, "Feature completed successfully")

    updated = store.get_task(task.id)
    assert TaskStatus(updated.status) == TaskStatus.DONE


@pytest.mark.asyncio
async def test_get_pending_tasks(task_manager: TaskManager, store: StateStore):
    """Test getting pending tasks."""
    workspace_id = task_manager.workspace_id

    store.upsert_agent(
        AgentRecord(
            workspace_id=workspace_id,
            name="worker-1",
            role=Role.BACKEND_CODER,
            status=AgentStatus.IDLE,
        )
    )

    store.upsert_agent(
        AgentRecord(
            workspace_id=workspace_id,
            name="worker-2",
            role=Role.FRONTEND_CODER,
            status=AgentStatus.IDLE,
        )
    )

    # Create tasks with different statuses
    task1 = await task_manager.create_task("Task 1", "Desc 1", "worker-1")
    task2 = await task_manager.create_task("Task 2", "Desc 2", "worker-2")
    task3 = await task_manager.create_task("Task 3", "Desc 3", "worker-1")

    await task_manager.mark_done(task2.id)

    # Get all pending tasks
    pending = task_manager.get_pending_tasks()
    assert len(pending) == 2
    pending_ids = {t.id for t in pending}
    assert task1.id in pending_ids
    assert task3.id in pending_ids
    assert task2.id not in pending_ids

    # Get pending tasks for specific agent
    worker1_pending = task_manager.get_pending_tasks(agent="worker-1")
    assert len(worker1_pending) == 2
    assert all(t.assigned_agent == "worker-1" for t in worker1_pending)


@pytest.mark.asyncio
async def test_get_active_tasks(task_manager: TaskManager, store: StateStore):
    """Test getting active tasks."""
    workspace_id = task_manager.workspace_id

    store.upsert_agent(
        AgentRecord(
            workspace_id=workspace_id,
            name="worker-1",
            role=Role.BACKEND_CODER,
            status=AgentStatus.IDLE,
        )
    )

    task1 = await task_manager.create_task("Task 1", "Desc 1", "worker-1")
    task2 = await task_manager.create_task("Task 2", "Desc 2", "worker-1")
    task3 = await task_manager.create_task("Task 3", "Desc 3", "worker-1")

    # Set different statuses
    store.update_task(task1.id, status=TaskStatus.RUNNING)
    store.update_task(task2.id, status=TaskStatus.ASSIGNED)
    store.update_task(task3.id, status=TaskStatus.DONE)

    active = task_manager.get_active_tasks()
    assert len(active) == 2
    active_ids = {t.id for t in active}
    assert task1.id in active_ids
    assert task2.id in active_ids
    assert task3.id not in active_ids
