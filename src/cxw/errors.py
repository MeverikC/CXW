class CXWError(Exception):
    """Base exception for CXW domain errors."""


class WorkspaceError(CXWError):
    """Raised when workspace identity or layout cannot be resolved."""


class DaemonError(CXWError):
    """Raised when the daemon cannot be reached or started."""


class ProtocolError(CXWError):
    """Raised when daemon IPC receives malformed data."""


class WorktreeError(CXWError):
    """Raised when git worktree management fails."""


class CodexRuntimeError(CXWError):
    """Raised when Codex runtime home or MCP setup fails."""
