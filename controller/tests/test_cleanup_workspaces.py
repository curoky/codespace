"""Tests for the stale workspace cleanup tool."""

from __future__ import annotations

from io import StringIO
from types import SimpleNamespace

import pytest
from rich.console import Console
from typer.testing import CliRunner

from controller import inventory
from controller.config import Config
from controller.models import HostDataPaths
from controller.tools import cleanup_workspaces


@pytest.fixture
def config() -> Config:
    return Config.model_validate(
        {
            "workspaces": {
                "defaults": {"image": "image", "container": {"network_mode": "host"}},
                "items": {
                    "devspace": {
                        "repo": "github:owner/repo",
                        "host": [{"name": "home"}],
                    }
                },
            },
            "hosts": {"home": {}},
        }
    )


@pytest.mark.parametrize(
    ("path", "active", "expected"),
    [
        (
            "/home/x/codespace/workspaces/devspace/live",
            {"/home/x/codespace/workspaces/devspace/live"},
            "yes",
        ),
        ("/home/x/codespace/workspaces/devspace/old", set(), "no"),
        ("/home/x/codespace/workspaces/Invalid/old", set(), "unmanaged"),
        ("/home/x/other/devspace/old", set(), "unmanaged"),
    ],
)
def test_usage(path: str, active: set[str], expected: str) -> None:
    assert cleanup_workspaces._usage("/home/x/codespace/workspaces", path, active) == expected


def test_scan_host_lists_instance_parents_once(
    monkeypatch: pytest.MonkeyPatch,
    config: Config,
) -> None:
    data_paths = HostDataPaths(root="/home/x/codespace")
    listed_roots: list[str] = []
    route = SimpleNamespace(host="home")
    transport = SimpleNamespace(
        client=lambda _host: object(),
        ssh_route=lambda _host: route,
    )
    current = inventory.Inventory(
        environments=[SimpleNamespace(workspace="devspace", instance="live")],  # type: ignore[list-item]
        errors=[],
    )
    monkeypatch.setattr(cleanup_workspaces.inventory, "list_inventory", lambda *args: current)
    monkeypatch.setattr(cleanup_workspaces.ssh, "remote_data_paths", lambda _route: data_paths)
    monkeypatch.setattr(
        cleanup_workspaces.ssh,
        "list_instances",
        lambda _route, root: (
            listed_roots.append(root)
            or [
                f"{root}/devspace/live",
                f"{root}/devspace/old",
            ]
        ),
    )

    scanned, active = cleanup_workspaces._scan_host(  # type: ignore[arg-type]
        config,
        transport,
        "home",
    )

    assert listed_roots == ["/home/x/codespace/workspaces"]
    assert scanned == [
        ("/home/x/codespace/workspaces", "/home/x/codespace/workspaces/devspace/live"),
        ("/home/x/codespace/workspaces", "/home/x/codespace/workspaces/devspace/old"),
    ]
    assert active == {"/home/x/codespace/workspaces/devspace/live"}


@pytest.mark.parametrize("arguments", [[], ["--no-dry-run"]])
def test_cli_only_deletes_unused_workspaces_with_no_dry_run(
    monkeypatch: pytest.MonkeyPatch,
    config: Config,
    arguments: list[str],
) -> None:
    root = "/home/x/codespace/workspaces"
    workspaces = [
        (
            "home",
            root,
            f"{root}/devspace/live",
            {f"{root}/devspace/live"},
        ),
        ("home", root, f"{root}/devspace/old", {f"{root}/devspace/live"}),
    ]
    output = StringIO()
    deleted: list[list[cleanup_workspaces.Workspace]] = []

    class FakeTransport:
        closed = False

        def close(self) -> None:
            self.closed = True

    transport = FakeTransport()
    monkeypatch.setattr(cleanup_workspaces, "console", Console(file=output, width=120))
    monkeypatch.setattr(cleanup_workspaces, "load_config", lambda _path: config)
    monkeypatch.setattr(cleanup_workspaces, "PodmanTransport", lambda _hosts: transport)
    monkeypatch.setattr(
        cleanup_workspaces,
        "_collect",
        lambda _config, _transport: (workspaces, []),
    )
    monkeypatch.setattr(
        cleanup_workspaces,
        "_delete",
        lambda _config, _transport, unused: (
            deleted.append(list(unused)) or len(unused),
            [],
        ),
    )

    result = CliRunner().invoke(cleanup_workspaces.app, arguments)

    assert result.exit_code == 0
    rendered = output.getvalue()
    assert "Host" in rendered
    assert "Workspace" in rendered
    assert "In use" in rendered
    assert f"{root}/devspace/live" in rendered
    assert f"{root}/devspace/old" in rendered
    assert transport.closed is True
    if arguments:
        assert deleted == [[("home", root, f"{root}/devspace/old")]]
        assert "Deleted 1 unused workspace(s)." in rendered
    else:
        assert deleted == []
        assert "Dry run: 1 unused workspace(s)" in rendered
