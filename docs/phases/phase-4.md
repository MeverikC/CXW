# Phase 4: Agents SDK Integration Boundary

Implemented:

- Built-in role prompts for planner, frontend-coder, backend-coder, tester, and reviewer.
- `AgentRuntime` protocol.
- Deterministic local runtime adapter that persists assignments and transparency fields.
- Optional OpenAI Agents SDK runtime selected with `CXW_AGENT_RUNTIME=openai-agents`.

Migration notes:

- The external OpenAI Agents SDK and Codex MCP adapter can be added behind `AgentRuntime`.
- No task or event schema changes are required for the first real adapter.
- Install the optional SDK dependency with `python -m pip install -e ".[agents]"`.
