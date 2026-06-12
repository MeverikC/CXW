# Phase 5: Real-Time Attach UI

Implemented:

- `cxw repo agent-name` streams agent events in a tail-like view.
- `cxw repo logs agent-name` replays persisted agent events without following.
- Main status view renders workspace, plan, agent status, recent events, and orchestrator decisions.

Migration notes:

- Attach uses the existing event stream protocol; no schema change.

