"""Tests for orphan Workspace cleanup."""

from __future__ import annotations

from io import StringIO
from types import SimpleNamespace

import pytest
from rich.console import Console

from codespace.config import Config
from codespace.maintenance import workspaces
from codespace.runtime.host import HostDataPaths


class FakeClient:
    def __init__(self, host: str) -> None:
        self.host = host
        self.closed = False

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *_args: object) -> None:
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
    config: Config, monkeypatch: pytest.MonkeyPatch, apply: bool
) -> None:
    paths = HostDataPaths("/home/x/codespace")
    live = paths.workspace("codespace", "live")
    old = paths.workspace("codespace", "old")
    manual = paths.workspace("Invalid", "manual")
    removed: list[tuple[str, str, str]] = []
    clients: list[FakeClient] = []
    options: list[dict[str, object]] = []

    def create_client(**kwargs: object) -> FakeClient:
        host_name = str(kwargs["base_url"]).removeprefix("http+ssh://").partition("/")[0]
        client = FakeClient(host_name)
        clients.append(client)
        options.append(kwargs)
        return client

    def inventory(_client: FakeClient, _host: str) -> list[SimpleNamespace]:
        return [SimpleNamespace(project="codespace", workspace="live")]

    monkeypatch.setattr(workspaces, "load_config", lambda _path: config)
    monkeypatch.setattr(workspaces, "PodmanClient", create_client)
    monkeypatch.setattr(workspaces.host, "remote_data_paths", lambda _route: paths)
    monkeypatch.setattr(workspaces.host, "list_workspaces", lambda *_args: [live, old, manual])
    monkeypatch.setattr(workspaces.inventory, "list_workspaces", inventory)
    monkeypatch.setattr(
        workspaces.container,
        "remove_data_directory",
        lambda client, image, _root, path: removed.append((client.host, image, path)),
    )
    stream = StringIO()

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
    assert {option["timeout"] for option in options} == {workspaces._CLIENT_TIMEOUT}
    assert ("Deleted 2" if apply else "Dry run: 2") in stream.getvalue()


def test_prune_fails_on_host_error(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def prune_host(
        host_name: str,
        _image: str,
        *,
        apply: bool,
    ) -> list[tuple[str, workspaces.Usage]]:
        assert apply is False
        if host_name == "office":
            raise RuntimeError("scan failed")
        return []

    monkeypatch.setattr(workspaces, "load_config", lambda _path: config)
    monkeypatch.setattr(workspaces, "_prune_host", prune_host)
    stream = StringIO()

    with pytest.raises(RuntimeError, match="scan failed"):
        workspaces.prune(apply=False, console=Console(file=stream, width=120))

    assert stream.getvalue() == ""
