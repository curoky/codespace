"""Tests for orphan Workspace cleanup."""

from __future__ import annotations

from io import StringIO
from threading import Barrier
from types import SimpleNamespace

import pytest
from rich.console import Console

from codespace.config import Config
from codespace.maintenance import workspaces
from codespace.runtime.host import HostDataPaths
from codespace.runtime.transport import SSHRoute

from .conftest import TransportInstaller


class FakeClient:
    def __init__(self, host: str) -> None:
        self.host = host
        self.closed = False

    def close(self) -> None:
        self.closed = True


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
def test_prune_only_deletes_unused_managed_workspaces(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
    install_transport: TransportInstaller,
    apply: bool,
) -> None:
    paths = HostDataPaths("/home/x/codespace")
    live = paths.workspace("codespace", "live")
    old = paths.workspace("codespace", "old")
    manual = paths.workspace("Invalid", "manual")
    removed: list[tuple[str, str, str]] = []
    clients: list[FakeClient] = []
    scanned: list[str] = []
    stream = StringIO()

    def create_client(host_name: str) -> FakeClient:
        client = FakeClient(host_name)
        clients.append(client)
        return client

    def inventory(_client: FakeClient, host_name: str) -> list[SimpleNamespace]:
        scanned.append(host_name)
        return [SimpleNamespace(project="codespace", workspace="live")]

    def remove(client: FakeClient, image: str, root: str, path: str) -> None:
        assert sorted(scanned) == ["home", "office"]
        assert "home" in stream.getvalue() and "office" in stream.getvalue()
        assert root == paths.workspaces
        assert client is next(item for item in clients if item.host == client.host)
        assert not client.closed
        removed.append((client.host, image, path))

    monkeypatch.setattr(workspaces, "load_config", lambda _path: config)
    options = install_transport(workspaces, create_client)

    def remote_data_paths(route: SSHRoute) -> HostDataPaths:
        assert route.control_path is not None
        return paths

    monkeypatch.setattr(workspaces.host, "remote_data_paths", remote_data_paths)
    monkeypatch.setattr(workspaces.host, "list_workspaces", lambda *_args: [live, old, manual])
    monkeypatch.setattr(workspaces.inventory, "list_workspaces", inventory)
    monkeypatch.setattr(workspaces.container, "remove_data_directory", remove)

    workspaces.prune(apply=apply, console=Console(file=stream, width=120))

    assert sorted(removed) == (
        [
            ("home", config.workspace_helper_image("home"), old),
            ("office", config.workspace_helper_image("office"), old),
        ]
        if apply
        else []
    )
    assert all(client.closed for client in clients)
    assert options == {"hosts": ["home", "office"], "client_timeout": workspaces._CLIENT_TIMEOUT}
    assert ("Deleted 2" if apply else "Dry run: 2") in stream.getvalue()


@pytest.mark.parametrize("apply", [False, True])
@pytest.mark.parametrize("failure", ["connect", "filesystem", "inventory"])
def test_prune_fails_on_host_error_without_deleting(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
    install_transport: TransportInstaller,
    apply: bool,
    failure: str,
) -> None:
    paths = HostDataPaths("/home/x/codespace")
    clients: list[FakeClient] = []
    removed: list[str] = []

    def create_client(host_name: str) -> FakeClient:
        if host_name == "office" and failure == "connect":
            raise RuntimeError("scan failed")
        client = FakeClient(host_name)
        clients.append(client)
        return client

    def list_paths(route: SSHRoute, _root: str) -> list[str]:
        if route.host == "office" and failure == "filesystem":
            raise RuntimeError("scan failed")
        return [paths.workspace("codespace", "old")]

    def inventory(_client: FakeClient, host_name: str) -> list[SimpleNamespace]:
        if host_name == "office" and failure == "inventory":
            raise RuntimeError("scan failed")
        return []

    monkeypatch.setattr(workspaces, "load_config", lambda _path: config)
    install_transport(workspaces, create_client)
    monkeypatch.setattr(workspaces.host, "remote_data_paths", lambda _route: paths)
    monkeypatch.setattr(workspaces.host, "list_workspaces", list_paths)
    monkeypatch.setattr(workspaces.inventory, "list_workspaces", inventory)
    monkeypatch.setattr(
        workspaces.container,
        "remove_data_directory",
        lambda _client, _image, _root, path: removed.append(path),
    )
    stream = StringIO()

    with pytest.raises(RuntimeError, match="scan failed"):
        workspaces.prune(apply=apply, console=Console(file=stream, width=120))

    assert stream.getvalue() == ""
    assert removed == []
    assert all(client.closed for client in clients)


def test_prune_scans_and_deletes_hosts_concurrently(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
    install_transport: TransportInstaller,
) -> None:
    clients = {host: FakeClient(host) for host in config.hosts}
    paths = HostDataPaths("/home/x/codespace")
    scanned = Barrier(len(clients))
    deleted = Barrier(len(clients))
    removed: list[str] = []

    def list_paths(route: SSHRoute, _root: str) -> list[str]:
        assert route.control_path is not None
        scanned.wait(timeout=5)
        return [paths.workspace("codespace", "old")]

    def remove(client: FakeClient, _image: str, _root: str, path: str) -> None:
        deleted.wait(timeout=5)
        assert not client.closed
        removed.append(path)

    monkeypatch.setattr(workspaces, "load_config", lambda _path: config)
    monkeypatch.setattr(workspaces.host, "remote_data_paths", lambda _route: paths)
    monkeypatch.setattr(workspaces.host, "list_workspaces", list_paths)
    monkeypatch.setattr(workspaces.inventory, "list_workspaces", lambda *_args: [])
    monkeypatch.setattr(workspaces.container, "remove_data_directory", remove)
    install_transport(workspaces, clients.__getitem__)

    workspaces.prune(apply=True, console=Console(file=StringIO()))

    assert len(removed) == len(clients)
    assert all(client.closed for client in clients.values())
