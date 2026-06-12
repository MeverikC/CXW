# Phase 6: Reviewer Workflow

Implemented:

- Review persistence model with `approve` and `request_changes` decisions.
- Review event emission through the event bus.
- Automatic review gate progression when all dispatched tasks are complete.
- Implementation branches receive persisted review decisions before merge planning.
- Review gate defaults to `request_changes` when no real reviewer runtime result has approved
  the branch, keeping the human review boundary explicit.
- Merge policy remains human-controlled through `final-approve`.

Migration notes:

- Reviews are persisted in the `reviews` table and can be replayed through events.
- Existing workspaces in `MONITOR` can resume into the review gate once all tasks are `done`.
