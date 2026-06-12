"""Tests for OpenAI Codex runtime."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cxw.agents.openai_codex_runtime import OpenAICodexRuntime
from cxw.events import EventBus
from cxw.models import AgentRecord, AgentStatus, Role, TaskRecord, TaskStatus
from cxw.store import StateStore
from cxw.workspace import WorkspaceLayout


@pytest.fixture
def mock_layout(tmp_path: Path) -> WorkspaceLayout:
    """Create a test workspace layout."""
    repo = tmp_path / "test-repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    return WorkspaceLayout.from_repo(repo)


@pytest.fixture
def store(mock_layout: WorkspaceLayout) -> StateStore:
    """Create a test state store."""
    mock_layout.ensure()
    store = StateStore(mock_layout)
    # Ensure workspace exists
    from cxw.models import WorkspaceRecord
    store.upsert_workspace(WorkspaceRecord(
        id=mock_layout.workspace_id,
        repo_path=str(mock_layout.repo_path),
    ))
    return store


@pytest.fixture
def bus(store: StateStore, mock_layout: WorkspaceLayout) -> EventBus:
    """Create a test event bus."""
    return EventBus(store, mock_layout.workspace_id)


@pytest.fixture
def runtime(store: StateStore, bus: EventBus, mock_layout: WorkspaceLayout) -> OpenAICodexRuntime:
    """Create runtime instance."""
    return OpenAICodexRuntime(store, bus, mock_layout, model="gpt-4o")


@pytest.mark.asyncio
async def test_runtime_dispatch_routes_by_role(runtime: OpenAICodexRuntime, store: StateStore):
    """Test that dispatch routes to correct handler based on role."""
    workspace_id = runtime.layout.workspace_id

    main_agent = store.upsert_agent(
        AgentRecord(
            workspace_id=workspace_id,
            name="main-1",
            role=Role.ORCHESTRATOR,
            status=AgentStatus.IDLE,
        )
    )

    worker_agent = store.upsert_agent(
        AgentRecord(
            workspace_id=workspace_id,
            name="worker-1",
            role=Role.BACKEND_CODER,
            status=AgentStatus.IDLE,
        )
    )

    task = store.create_task(
        TaskRecord(
            workspace_id=workspace_id,
            title="Test task",
            description="Test description",
            assigned_agent="main-1",
        )
    )

    with patch.object(runtime, "_dispatch_main_agent", new_callable=AsyncMock) as mock_main:
        with patch.object(runtime, "_dispatch_worker_agent", new_callable=AsyncMock) as mock_worker:
            await runtime.dispatch(main_agent, task)
            mock_main.assert_called_once()
            mock_worker.assert_not_called()

    with patch.object(runtime, "_dispatch_main_agent", new_callable=AsyncMock) as mock_main:
        with patch.object(runtime, "_dispatch_worker_agent", new_callable=AsyncMock) as mock_worker:
            task.assigned_agent = "worker-1"
            await runtime.dispatch(worker_agent, task)
            mock_worker.assert_called_once()
            mock_main.assert_not_called()


@pytest.mark.asyncio
async def test_build_codex_tools(runtime: OpenAICodexRuntime, store: StateStore):
    """Test that codex tools are built for each worker agent."""
    workspace_id = runtime.layout.workspace_id

    store.upsert_agent(
        AgentRecord(
            workspace_id=workspace_id,
            name="main-1",
            role=Role.ORCHESTRATOR,
            status=AgentStatus.IDLE,
        )
    )

    store.upsert_agent(
        AgentRecord(
            workspace_id=workspace_id,
            name="backend-1",
            role=Role.BACKEND_CODER,
            status=AgentStatus.IDLE,
        )
    )

    store.upsert_agent(
        AgentRecord(
            workspace_id=workspace_id,
            name="frontend-1",
            role=Role.FRONTEND_CODER,
            status=AgentStatus.IDLE,
        )
    )

    tools = runtime._build_codex_tools()

    assert len(tools) == 2  # Only workers, not orchestrator
    tool_names = [t["function"]["name"] for t in tools]
    assert "codex_backend_1" in tool_names
    assert "codex_frontend_1" in tool_names
    assert "codex_main_1" not in tool_names

    # Check tool structure
    backend_tool = next(t for t in tools if t["function"]["name"] == "codex_backend_1")
    assert backend_tool["type"] == "function"
    assert "task_description" in backend_tool["function"]["parameters"]["properties"]
    assert "context" in backend_tool["function"]["parameters"]["properties"]


def test_format_task_prompt(runtime: OpenAICodexRuntime, store: StateStore):
    """Test task prompt formatting."""
    workspace_id = runtime.layout.workspace_id

    task = TaskRecord(
        workspace_id=workspace_id,
        title="Build API",
        description="Create REST API with FastAPI",
        assigned_agent="backend-1",
    )

    prompt = runtime._format_task_prompt(task)

    assert "Build API" in prompt
    assert "Create REST API with FastAPI" in prompt
    assert "Goal:" in prompt


def test_extract_codex_output(runtime: OpenAICodexRuntime):
    """Test extraction of various Codex output formats."""
    # Structured content format
    result1 = {
        "structuredContent": {
            "threadId": "thread-123",
            "content": "Task completed successfully",
        }
    }
    thread_id, content = runtime._extract_codex_output(result1)
    assert thread_id == "thread-123"
    assert content == "Task completed successfully"

    # Direct format
    result2 = {
        "threadId": "thread-456",
        "content": "Another completion",
    }
    thread_id, content = runtime._extract_codex_output(result2)
    assert thread_id == "thread-456"
    assert content == "Another completion"

    # Content array format
    result3 = {
        "content": [
            {"text": "Part 1"},
            {"text": "Part 2"},
        ]
    }
    thread_id, content = runtime._extract_codex_output(result3)
    assert thread_id is None
    assert content == "Part 1\nPart 2"

    # Fallback format
    result4 = {"unknown": "format"}
    thread_id, content = runtime._extract_codex_output(result4)
    assert thread_id is None
    assert "unknown" in content


@pytest.mark.asyncio
async def test_handle_tool_call_success(runtime: OpenAICodexRuntime, store: StateStore):
    """Test successful tool call handling."""
    workspace_id = runtime.layout.workspace_id

    main_agent = store.upsert_agent(
        AgentRecord(
            workspace_id=workspace_id,
            name="main-1",
            role=Role.ORCHESTRATOR,
            status=AgentStatus.RUNNING,
        )
    )

    worker_agent = store.upsert_agent(
        AgentRecord(
            workspace_id=workspace_id,
            name="backend-1",
            role=Role.BACKEND_CODER,
            status=AgentStatus.IDLE,
            worktree_path=str(runtime.layout.repo_path / "worktrees" / "backend-1"),
        )
    )

    # Mock tool call
    tool_call = MagicMock()
    tool_call.id = "call-123"
    tool_call.function.name = "codex_backend_1"
    tool_call.function.arguments = '{"task_description": "Create API", "context": "Use FastAPI"}'

    # Mock Codex MCP client
    with patch("cxw.agents.openai_codex_runtime.McpStdioClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.initialize.return_value = {"serverInfo": {"name": "codex"}}
        mock_client.call_tool.return_value = {
            "threadId": "thread-789",
            "content": "API created successfully",
        }
        mock_client_class.return_value = mock_client

        with patch("cxw.agents.openai_codex_runtime.CodexHomeManager") as mock_home_manager:
            mock_home = MagicMock()
            mock_home.env.return_value = {}
            mock_home_manager.return_value.prepare_agent_home.return_value = mock_home

            result = await runtime._handle_tool_call(main_agent, tool_call)

    assert result["status"] == "completed"
    assert result["agent"] == "backend-1"
    assert result["thread_id"] == "thread-789"
    assert "API created successfully" in result["output"]

    # Check agent status was updated
    updated_agent = store.get_agent(workspace_id, "backend-1")
    assert AgentStatus(updated_agent.status) == AgentStatus.COMPLETED


@pytest.mark.asyncio
async def test_handle_tool_call_failure(runtime: OpenAICodexRuntime, store: StateStore):
    """Test tool call failure handling."""
    workspace_id = runtime.layout.workspace_id

    main_agent = store.upsert_agent(
        AgentRecord(
            workspace_id=workspace_id,
            name="main-1",
            role=Role.ORCHESTRATOR,
            status=AgentStatus.RUNNING,
        )
    )

    worker_agent = store.upsert_agent(
        AgentRecord(
            workspace_id=workspace_id,
            name="backend-1",
            role=Role.BACKEND_CODER,
            status=AgentStatus.IDLE,
        )
    )

    tool_call = MagicMock()
    tool_call.id = "call-456"
    tool_call.function.name = "codex_backend_1"
    tool_call.function.arguments = '{"task_description": "Invalid task"}'

    with patch("cxw.agents.openai_codex_runtime.McpStdioClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.initialize.return_value = {}
        mock_client.call_tool.side_effect = Exception("MCP error")
        mock_client_class.return_value = mock_client

        with patch("cxw.agents.openai_codex_runtime.CodexHomeManager") as mock_home_manager:
            mock_home = MagicMock()
            mock_home.env.return_value = {}
            mock_home_manager.return_value.prepare_agent_home.return_value = mock_home

            result = await runtime._handle_tool_call(main_agent, tool_call)

    assert result["status"] == "failed"
    assert result["agent"] == "backend-1"
    assert "MCP error" in result["error"]

    # Check agent status was marked failed
    updated_agent = store.get_agent(workspace_id, "backend-1")
    assert AgentStatus(updated_agent.status) == AgentStatus.FAILED


def test_handle_unknown_tool(runtime: OpenAICodexRuntime, store: StateStore):
    """Test handling of unknown tool calls."""
    workspace_id = runtime.layout.workspace_id

    main_agent = store.upsert_agent(
        AgentRecord(
            workspace_id=workspace_id,
            name="main-1",
            role=Role.ORCHESTRATOR,
            status=AgentStatus.RUNNING,
        )
    )

    tool_call = MagicMock()
    tool_call.function.name = "unknown_tool"

    result = asyncio.run(runtime._handle_tool_call(main_agent, tool_call))

    assert "error" in result
    assert "unknown tool" in result["error"]
