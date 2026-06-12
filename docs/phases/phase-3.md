# Phase 3: Worktree Manager

Implemented:

- Git worktree creation under the CXW workspace data directory.
- Branch naming as `cxw/<agent-name>`.
- Store-level uniqueness for `(workspace_id, worktree_path)`.
- Runtime checks preventing another agent from claiming an owned worktree.

Migration notes:

- Worktree paths are persisted on agent records.
- CXW never removes worktrees automatically in this phase.

