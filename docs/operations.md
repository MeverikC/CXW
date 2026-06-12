# CXW Operations Guide

This guide covers migration, backup, recovery, and troubleshooting.

## Local State Locations

CXW source code can live anywhere. Runtime state is stored under:

```text
~/.cxw/workspaces/<workspace_id>
```

Each workspace contains:

```text
state.sqlite3
events.ndjson
run/endpoint.json
logs/
worktrees/
```

`run/endpoint.json` is runtime metadata and can be regenerated. SQLite and NDJSON
are the durable recovery sources.

The target repository should also contain `CXW.toml`. If it does not, CXW creates
a template and waits for the user to complete the agent and task plan.

CXW also prepares repository-local Codex homes:

```text
<repo>/.codex/cxw/main-1
<repo>/.codex/cxw/agents/<agent-name>
```

These directories contain copied Codex auth when available. They must remain
local and untracked; CXW adds `.codex/` to `.gitignore`.

## Move CXW To Another Device

Copy the CXW project directory, then install:

```powershell
cd C:\path\to\cxw
python -m pip install -e ".[dev]"
python -m pytest -p no:cacheprovider
```

If you only copy the source code, the new device starts fresh workspace state.

To migrate history too, copy:

```text
~/.cxw/workspaces/<workspace_id>
```

Important: `workspace_id` is based on the absolute repository path. If the target
repo path changes on the new device, CXW will compute a different workspace id.
Use backup/restore tooling or keep the same absolute repo path when possible.

## Backup Strategy

Back up:

- `state.sqlite3`
- `events.ndjson`
- `logs/`
- `worktrees/` if you want local branches and worktree files preserved

Do not rely on `run/endpoint.json`; it only points to the current daemon endpoint.
Do not back up or share repository `.codex/` directories unless you explicitly
intend to move local Codex credentials.

Create a backup:

```powershell
cxw C:\path\to\repo backup
```

Restore to a target repo path:

```powershell
cxw restore C:\backups\workspace.cxw.zip C:\path\to\repo
```

Restore behavior:

- The target workspace id is recomputed from the target absolute repo path.
- SQLite workspace ids are rewritten to the target workspace id.
- `events.ndjson` top-level workspace ids are rewritten for replay consistency.
- `run/endpoint.json` is excluded because it is transient.
- Existing target workspace files are not overwritten.

## Recovery

If a daemon is not running, any CLI command starts a new daemon and reconnects to
the existing workspace state.

Use:

```powershell
cxw C:\path\to\repo resume
cxw C:\path\to\repo status
```

The daemon publishes a recovery event and renders the persisted state.

Management commands:

```powershell
cxw workspaces
cxw C:\path\to\repo daemon-health
cxw C:\path\to\repo workspace-info
cxw C:\path\to\repo daemon-stop
```

`daemon-health` and `daemon-stop` do not start a stopped daemon.

## Troubleshooting

Daemon does not start:

- Check `~/.cxw/workspaces/<workspace_id>/logs/daemon.stderr.log`.
- Verify Python can import CXW with `python -m cxw --help`.
- Verify the repo path exists.

Worktree creation fails:

- Verify the target repo is a git repository.
- Verify the repo has at least one commit.
- Run `git worktree list` in the target repo.

Agent stream is empty:

- Use `cxw repo logs agent-name` to replay persisted events.
- Use `cxw repo status` to verify the agent exists.
- Check whether the agent is stopped.

Interactive shell does not appear:

- Use a real terminal, not a non-interactive command runner.
- Force the shell with `cxw repo --interactive` or `cxw repo shell`.
- Use `cxw repo --no-interactive` when you explicitly want one status render.
- Verify `prompt_toolkit` is installed in the active environment:
  `python -c "import prompt_toolkit; print(prompt_toolkit.__version__)"`.
- Reinstall the current checkout if needed: `python -m pip install -e .`.

Repository `.codex/` is missing:

- Run `cxw repo status` or `cxw repo config-check`; workspace initialization
  prepares `<repo>/.codex/cxw/main-1`.
- Check that you are looking at the target repository root, not
  `~/.cxw/workspaces/<workspace_id>`.
- If `auth.json` is missing inside the home, run Codex login in your normal
  Codex home and then rerun `cxw repo status`.

Codex MCP runtime fails:

- Verify `codex mcp-server` starts.
- Verify `CXW.toml` declares `[defaults.codex] runtime = "codex-mcp"`, or run
  with `cxw repo run --runtime codex-mcp`, or set `CXW_AGENT_RUNTIME=codex-mcp`.
- Verify `<repo>/.codex/cxw/main-1/auth.json` or
  `<repo>/.codex/cxw/agents/<agent>/auth.json` exists, or Codex can
  authenticate through the generated home.
- Use `CXW_CODEX_MCP_COMMAND` if the executable path differs.

Optional OpenAI runtime fails:

- Install `python -m pip install -e ".[agents]"`.
- Verify API credentials required by the OpenAI SDK are available in the shell.
- Switch back to the deterministic runtime with `cxw repo run --runtime local-deterministic`
  or by unsetting `CXW_AGENT_RUNTIME` when the project config does not explicitly
  choose another runtime.
