"""Tests for orphan Workspace cleanup."""

from io import StringIO
from types import SimpleNamespace

import pytest
from rich.console import Console

from codespace.config import Config
from codespace.maintenance import workspaces
from codespace.runtime.host import HostDataPaths


@pytest.mark.parametrize(
    ("path", "active", "expected"),
    [
        (
            "/home/x/codespace/workspaces/codespace/live",
            {"/home/x/codespace/workspaces/codespace/live"},
            "yes",
        ),
        ("/home/x/codespace/workspaces/codespace/old", set(), "no"),
        ("/home/x/codespace/workspaces/Invalid/old", set(), "unmanaged"),
        ("/home/x/other/codespace/old", set(), "unmanaged"),
    ],
)
def test_usage(path: str, active: set[str], expected: str) -> None:
    assert workspaces._usage("/home/x/codespace/workspaces", path, active) == expected


@pytest.mark.parametrize("apply", [False, True])
def test_prune_executes_only_unused_candidates_from_successful_hosts(
    config: Config, monkeypatch: pytest.MonkeyPatch, apply: bool
) -> None:
    paths = HostDataPaths("/home/x/codespace")
    live = paths.workspace("codespace", "live").root
    old = paths.workspace("codespace", "old").root
    manual = paths.workspace("Invalid", "manual").root
    removed: list[tuple[str, str, str]] = []
    closed: list[bool] = []
    transport = SimpleNamespace(
        ssh_route=lambda host: host, client=lambda host: host, close=lambda: closed.append(True)
    )

    def inventory(client: str, _host: str) -> list[SimpleNamespace]:
        if client == "office":
            raise RuntimeError("scan failed")
        return [SimpleNamespace(project="codespace", workspace="live")]

    monkeypatch.setattr(workspaces, "load_config", lambda _path: config)
    monkeypatch.setattr(workspaces, "PodmanTransport", lambda _hosts: transport)
    monkeypatch.setattr(workspaces.host, "remote_data_paths", lambda _route: paths)
    monkeypatch.setattr(workspaces.host, "list_workspaces", lambda *_args: [live, old, manual])
    monkeypatch.setattr(workspaces.inventory, "list_workspaces", inventory)
    monkeypatch.setattr(
        workspaces.container,
        "remove_data_directory",
        lambda client, image, _root, path: removed.append((client, image, path)),
    )
    stream = StringIO()

    workspaces.prune(apply=apply, console=Console(file=stream, width=120))

    assert removed == ([("home", config.project_defaults.image, old)] if apply else [])
    assert "scan failed" in stream.getvalue()
    assert closed == [True]
