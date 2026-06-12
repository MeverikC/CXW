# CXW Workspace Management

## List All Workspaces

```bash
# Show all workspaces with status
cxw workspaces

# JSON output
cxw workspaces --json
```

Output shows:
- Workspace ID (first 12 chars)
- Current state (INIT, RUNNING, etc.)
- Daemon status
- Number of agents and events
- Repository path

## Clean Workspace Cache

When you delete and recreate a directory, the workspace ID now changes automatically (based on `.git` creation time), but you can also manually clean old caches:

```bash
# Remove specific workspace by ID
cxw clean <workspace_id>

# Remove all workspaces
cxw clean all
```

### Examples

```bash
# List workspaces
$ cxw workspaces
                Known Workspaces                
┏━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ Workspace ID   ┃ State          ┃ Daemon     ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━┩
│ 04be75f65a37   │ INIT           │ stopped    │
│ 7c1b487a587d   │ RUNNING        │ running    │
└────────────────┴────────────────┴────────────┘

# Remove specific workspace
$ cxw clean 04be75f65a37f5991b3e64a9adcb5a3a5fa4907a1aa5b5c984f5c23373bb45db
Removed workspace: 04be75f65a37

# Remove all workspaces (careful!)
$ cxw clean all
Removed 138 workspace(s)
```

## Workspace ID Generation

Workspace ID is generated as:
```
sha256(absolute_repo_path + .git_creation_time)
```

This means:
- Same path = same workspace (reuse cache)
- Delete and recreate directory = new workspace ID (fresh cache)
- Move directory = new workspace ID

## Automatic Cache Invalidation

When you delete a directory and recreate it:

1. Old behavior:
   - Workspace ID based only on path
   - Cache persisted even after directory recreation
   - Had to manually clean

2. New behavior:
   - Workspace ID includes `.git` creation time
   - Deleting directory changes creation time
   - New workspace ID = automatic fresh cache
   - Old cache becomes orphaned (can be cleaned with `cxw clean all`)

## Workspace Data Location

All workspace data stored in:
```
~/.cxw/workspaces/<workspace_id>/
  ├── state.sqlite3      # SQLite state store
  ├── events.ndjson      # Event log
  ├── logs/              # Daemon logs
  ├── run/               # Runtime files (endpoint)
  └── worktrees/         # Git worktrees
```

## Best Practices

1. **Regular cleanup**: Periodically run `cxw workspaces` and clean old/unused workspaces
2. **Before major changes**: Clean workspace if experiencing issues
3. **After directory recreation**: The new workspace ID is automatic
4. **Storage management**: Use `cxw clean all` to reclaim disk space

## JSON API

```bash
# List workspaces
cxw workspaces --json
# {"ok": true, "workspaces": [...]}

# Clean workspace
cxw clean <id> --json
# {"ok": true, "removed": 1, "workspace_id": "..."}

# Clean all
cxw clean all --json
# {"ok": true, "removed": 138}
```

## Safety

- `cxw clean` only removes workspace cache (in `~/.cxw/`)
- Your actual repository is never touched
- Git worktrees are under workspace cache, so they're also cleaned
- Always safe to clean and start fresh
