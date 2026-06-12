# Codex MCP Runtime + Prompt Toolkit Tasks

Goal: make CXW usable as a persistent terminal orchestration workspace that can prepare isolated Codex MCP agent homes and later run real Codex subagents.

## Tasks

- [x] Create this task tracker so implementation can resume safely after context compaction.
- [x] Add Codex home/config manager.
  - Prepare `<repo>/.codex/cxw/main-1` and `<repo>/.codex/cxw/agents/<agent-name>`.
  - Copy current Codex `auth.json` without logging secrets.
  - Merge model/base_url/provider overrides into per-agent `config.toml`.
  - Ensure repo `.gitignore` excludes `.codex/`.
- [x] Extend `CXW.toml` schema for main agent, runtime defaults, agent runtime settings, and goal-mode safeguards.
- [x] Add prompt_toolkit dependency and interactive workspace shell skeleton.
- [x] Add a Codex MCP stdio client spike that can initialize/list tools, call the real `codex` tool, and emit audit events.
- [x] Wire runtime selection through daemon/orchestrator without breaking deterministic tests.
- [x] Replace keyword-triggered planning with structured `/plan` and `cxw <repo> plan ...` commands.
- [x] Add structured execution entrypoints: `/run` and `cxw <repo> run [--runtime <name>]`.
- [x] Keep `approve-plan` and `/approve` as legacy aliases while making `run` the documented path.
- [x] Update README/user/agent/developer/operations docs for the current command surface.
- [x] Add focused tests and update this checklist.

## Non-Goals In This Batch

- Full autonomous merge.
- Full multi-agent scheduling policy rewrite.
- Fine-grained Codex event streaming from the MCP session.
- Web UI.
- Exposing Codex auth contents in events or logs.
