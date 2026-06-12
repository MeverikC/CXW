from __future__ import annotations

from cxw.ipc import TransportKind, endpoint_from_layout
from cxw.workspace import WorkspaceLayout


def test_long_workspace_paths_use_tcp_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("CXW_HOME", str(tmp_path / ("x" * 80)))
    repo = tmp_path / "repo"
    repo.mkdir()

    endpoint = endpoint_from_layout(WorkspaceLayout.from_repo(repo))

    assert endpoint.kind == TransportKind.TCP
