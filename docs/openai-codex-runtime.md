# OpenAI Codex Runtime

Multi-agent orchestration runtime that exposes Codex MCP agents as OpenAI SDK tools.

## Overview

The `openai-codex` runtime enables a main orchestrator agent (powered by OpenAI models like GPT-4) to control multiple Codex worker agents through tool calls. Each worker agent runs in an isolated git worktree with its own Codex MCP server instance.

## Architecture

```
┌─────────────────────────────────────────┐
│   Main Orchestrator Agent (GPT-4)      │
│   - Plans & decomposes tasks            │
│   - Coordinates execution                │
│   - Handles failures & adjustments       │
└─────────────────┬───────────────────────┘
                  │
      ┌───────────┼───────────┐
      │           │           │
      ▼           ▼           ▼
┌──────────┐ ┌──────────┐ ┌──────────┐
│ Codex    │ │ Codex    │ │ Codex    │
│ Worker 1 │ │ Worker 2 │ │ Worker 3 │
│          │ │          │ │          │
│ Worktree │ │ Worktree │ │ Worktree │
│ cxw/w1   │ │ cxw/w2   │ │ cxw/w3   │
└──────────┘ └──────────┘ └──────────┘
```

## Usage

### 1. Configure Runtime

Set the runtime in `CXW.toml`:

```toml
[defaults.codex]
runtime = "openai-codex"
model = "gpt-4o"  # Main orchestrator model
goal_mode = true
approval_policy = "on-request"
sandbox_mode = "workspace-write"
```

Or via environment:

```bash
export CXW_AGENT_RUNTIME=openai-codex
export CXW_OPENAI_MODEL=gpt-4o
export OPENAI_API_KEY=sk-...
```

### 2. Define Agents

Each worker agent gets its own Codex home and can have custom API settings:

```toml
[[agents]]
name = "frontend-1"
role = "frontend-coder"
instructions = "Build React frontend with Tailwind"

[agents.codex]
model = "claude-opus-4"
base_url = "https://api.anthropic.com/v1"
# Each agent can use different API key via environment

[[agents]]
name = "backend-1"
role = "backend-coder"
instructions = "Build FastAPI backend"

[agents.codex]
model = "gpt-4o-mini"
# Uses OpenAI API for this worker
```

### 3. Run Orchestration

```bash
cd your-project
cxw . run --runtime openai-codex
```

The main agent will:
1. Analyze the workspace goal
2. Break it into subtasks
3. Call `codex_frontend_1(task_description="...")` and `codex_backend_1(...)` tools
4. Coordinate execution and handle results
5. Adjust plan dynamically based on outcomes

## Tool Interface

The main orchestrator gets one tool per worker agent:

```python
codex_<agent_name>(
    task_description: str,  # What the agent should do
    context: str = ""       # Additional context from previous work
) -> dict
```

Tool returns:
```json
{
  "status": "completed" | "failed",
  "agent": "worker-name",
  "thread_id": "codex-thread-id",
  "output": "execution summary",
  "error": "error message if failed"
}
```

## Dynamic Planning

The orchestrator can adjust plans mid-execution:

- **Requirement clarification**: If a worker reveals unclear requirements, the orchestrator refines and re-dispatches
- **Dependency discovery**: Add new tasks when implementation reveals missing dependencies
- **Failure recovery**: Analyze errors and retry with clarified instructions or pivot strategy

Example flow:
```
1. Main: "Build todo app"
2. Main → codex_backend_1("Create API endpoints")
3. Backend completes with schema details
4. Main → codex_frontend_1("Build UI", context=<API schema>)
5. Frontend reports CORS issue
6. Main → codex_backend_1("Add CORS middleware", context=<frontend origin>)
7. Main → codex_tester_1("Verify integration")
```

## Interruption Handling

Workers **cannot be interrupted** mid-execution. When the plan needs adjustment:

1. **Wait for completion**: Let current task finish, then dispatch adjusted task
2. **Queue replacement**: Mark task as adjusted, worker picks up new version next
3. **Log decision**: Record why and what changed for audit trail

The orchestrator system prompt includes this constraint and plans accordingly.

## Per-Agent API Configuration

Each agent can use different LLM APIs:

### Example: Multi-Provider Setup

```toml
[[agents]]
name = "planner-1"
role = "planner"
[agents.codex]
model = "claude-sonnet-4"
base_url = "https://api.anthropic.com/v1"

[[agents]]
name = "coder-1"
role = "backend-coder"
[agents.codex]
model = "gpt-4o"
# Uses OpenAI by default

[[agents]]
name = "reviewer-1"
role = "reviewer"
[agents.codex]
model = "deepseek-coder"
base_url = "https://api.deepseek.com/v1"
```

API keys per agent via environment:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
export DEEPSEEK_API_KEY=sk-...
```

Codex MCP automatically picks the right auth based on `base_url`.

## Cost Tracking

Each agent's Codex home is isolated, so you can:
- Track token usage per agent via Codex logs
- Separate billing by using different API keys
- Monitor which agents consume the most resources

Logs location:
```
<repo>/.codex/cxw/agents/<agent-name>/logs/
```

## System Prompt Strategy

### Main Orchestrator Prompt

- Emphasizes **task decomposition** and **clear acceptance criteria**
- Teaches **dynamic planning**: adjust when reality differs from plan
- Explains **no-interrupt constraint**: wait for task completion before adjusting
- Provides **failure taxonomy**: retriable vs. plan-adjustment needed

### Worker Prompts

- Focused on **execution within scope**
- Report **blockers immediately** rather than trying workarounds
- Commit work to branch for orchestrator to review
- Include **verification steps** in task completion

## Example Workflow

User goal: "Build lottery drawing app with React + FastAPI"

Main orchestrator execution:

```
[Planning]
Main: Analyzing requirement...
Main: Need: backend API, frontend UI, state management, deployment
Main: Agents available: backend-1, frontend-1, tester-1

[Execution Phase 1]
Main: Dispatching backend task...
Main → codex_backend_1("Create lottery API with draw endpoint...")
Backend-1: [worktree cxw/backend-1] Building FastAPI app...
Backend-1: Completed. Endpoints: POST /draw, GET /history

[Execution Phase 2] 
Main: Backend complete. Dispatching frontend...
Main → codex_frontend_1("Build React UI", context="API at /draw, /history")
Frontend-1: [worktree cxw/frontend-1] Building React app...
Frontend-1: Completed. UI ready.

[Validation]
Main → codex_tester_1("Run integration tests")
Tester-1: Tests failing - CORS not configured

[Recovery]
Main: Test failure indicates CORS issue. Re-dispatching backend fix...
Main → codex_backend_1("Add CORS middleware for frontend origin")
Backend-1: CORS configured.

[Re-validation]
Main → codex_tester_1("Retry integration tests")
Tester-1: All tests passing.

[Summary]
Main: Lottery app complete. Backend in cxw/backend-1, frontend in cxw/frontend-1.
Main: Next: user review branches and approve merge.
```

## Monitoring

Real-time progress tracking:

```bash
# Watch multi-agent progress
cxw . status --watch

# Stream events
cxw . events --follow
```

Shows:
- Which agents are active
- Current task per agent
- Tool calls (codex invocations)
- Failures and retries
- Plan adjustments

## Comparison to Other Runtimes

| Runtime | Main Agent | Workers | Coordination |
|---------|-----------|---------|--------------|
| `local-deterministic` | None | None | Dry-run only |
| `codex-mcp` | Codex MCP | Codex MCP | Static plan from CXW.toml |
| `openai-agents` | OpenAI SDK | OpenAI SDK | OpenAI agent framework |
| **`openai-codex`** | **OpenAI SDK** | **Codex MCP** | **Dynamic planning + Codex execution** |

Benefits of `openai-codex`:
- **Smart orchestration**: GPT-4 does planning, Codex does implementation
- **Cost-effective**: Use expensive model only for coordination
- **Flexible**: Mix OpenAI/Anthropic/DeepSeek models per agent
- **Auditable**: Every decision and execution logged

## Limitations

1. **No real-time interrupts**: Must wait for task completion to adjust
2. **Main agent cost**: GPT-4 runs for entire orchestration session
3. **Tool call overhead**: Each worker dispatch is a round-trip
4. **No agent-to-agent communication**: All coordination via main agent

For simple linear workflows, `codex-mcp` runtime may be more efficient.

## Troubleshooting

### "OpenAI SDK not installed"

```bash
pip install openai
```

### "Codex MCP server not found"

Ensure Codex CLI is installed and available:

```bash
which codex
export CXW_CODEX_BIN=/path/to/codex
```

### Main agent loops without progress

Check orchestrator is receiving tool results. Enable debug logging:

```bash
export CXW_LOG_LEVEL=debug
cxw . run --runtime openai-codex
```

### Worker fails with auth error

Ensure API key environment variable matches the worker's base_url:

```bash
export ANTHROPIC_API_KEY=...  # for Anthropic agents
export OPENAI_API_KEY=...     # for OpenAI agents
```

## Future Enhancements

- [ ] Real-time interrupt support (when Codex MCP adds it)
- [ ] Streaming worker progress to main agent
- [ ] Cost tracking dashboard per agent
- [ ] Agent result caching for idempotent tasks
- [ ] Multi-round conversation between main and workers
