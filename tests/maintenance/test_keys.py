"""Tests for unused deploy-key classification."""

from io import StringIO
from types import SimpleNamespace

import pytest
from rich.console import Console

from codespace.config import Config
from codespace.maintenance import keys
from codespace.workspaces.provider import DeployKey


@pytest.mark.parametrize(
    ("title", "active", "scanned", "expected"),
    [
        (
            "codespace-workspace_home_codespace_live",
            {"codespace-workspace_home_codespace_live"},
            {"home"},
            "yes",
        ),
        ("codespace-workspace_home_codespace_old", set(), {"home"}, "no"),
        ("codespace-workspace_office_codespace_live", set(), {"home"}, "unknown"),
        ("manual-key", set(), {"home"}, "unmanaged"),
    ],
)
def test_usage(
    title: str,
    active: set[str],
    scanned: set[str],
    expected: str,
) -> None:
    routes = [("home", "codespace"), ("office", "codespace")]

    assert keys._usage(title, routes, active, scanned) == expected


@pytest.mark.parametrize("apply", [False, True])
def test_prune_deletes_only_planned_unused_keys(
    config: Config, monkeypatch: pytest.MonkeyPatch, apply: bool
) -> None:
    data = config.model_dump()
    data["tokens"] = {"github": "test-token"}
    configured = Config.model_validate(data)
    active = configured.workspace_spec("codespace", "home", "live").to_workspace(
        "container-id", status="running"
    )
    listed = [
        DeployKey(1, active.id),
        DeployKey(2, "codespace-workspace_home_codespace_old"),
        DeployKey(3, "manual-key"),
    ]
    deleted: list[list[int]] = []
    transport = SimpleNamespace(client=lambda _host: object(), close=lambda: None)
    monkeypatch.setattr(keys, "load_config", lambda _path: configured)
    monkeypatch.setattr(keys, "PodmanTransport", lambda _hosts: transport)
    monkeypatch.setattr(keys.inventory, "list_workspaces", lambda *_args: [active])
    monkeypatch.setattr(keys.provider, "list_deploy_keys", lambda *_args: listed)
    monkeypatch.setattr(
        keys.provider,
        "delete_deploy_keys",
        lambda _provider, _token, _repo, ids: deleted.append(ids),
    )

    keys.prune(apply=apply, console=Console(file=StringIO(), width=120))

    assert deleted == ([[2]] if apply else [])
