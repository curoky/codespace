"""Tests for Workspace SSH login probes."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from codespace.runtime.transport import SSHRoute
from codespace.workspaces import (
    ProviderSource,
    Workspace,
    ssh,
)


def _workspace(name: str = "debug") -> Workspace:
    return Workspace(
        project="codespace",
        workspace=name,
        host="home",
        source=ProviderSource(type="github", repository="curoky/codespace"),
        image="workspace:latest",
        platform="native",
        open_path="/workspace/codespace",
        encrypted=False,
        container_id=f"container-{name}",
        status="running",
    )


def test_probe_uses_preprovisioned_config_and_existing_host_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []
    config = tmp_path / "config"
    monkeypatch.setattr(ssh, "SSH_CONFIG_PATH", config)
    monkeypatch.setattr(
        ssh.subprocess,
        "run",
        lambda command, **_kwargs: commands.append(command),
    )

    ssh.probe(_workspace(), SSHRoute(host="home", control_path=Path("/tmp/host.sock")))

    assert commands == [
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-F",
            str(config),
            "-o",
            f"Port={_workspace().ssh_host_port}",
            "-o",
            "ProxyCommand=ssh -o BatchMode=yes -o ControlPath=/tmp/host.sock -W %h:%p home",
            _workspace().ssh_alias,
            "true",
        ]
    ]


def test_write_route_persists_workspace_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routes = tmp_path / "workspaces"
    monkeypatch.setattr(ssh, "SSH_ROUTES_DIR", routes)
    workspace = _workspace()

    ssh.write_route(workspace)

    route = routes / workspace.ssh_alias
    assert route.read_text() == (
        "Host space-codespace-debug-home\n"
        "  HostName 127.0.0.1\n"
        f"  Port {workspace.ssh_host_port}\n"
        "  ProxyCommand ssh -o BatchMode=yes -W %h:%p home\n"
    )
    assert stat.S_IMODE(routes.stat().st_mode) == 0o700
    assert stat.S_IMODE(route.stat().st_mode) == 0o600


def test_write_route_replaces_only_the_target_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routes = tmp_path / "workspaces"
    routes.mkdir()
    untouched = routes / "space-scratch-shell-home"
    untouched.write_text("other route\n")
    target = routes / _workspace().ssh_alias
    target.write_text("stale route\n")
    monkeypatch.setattr(ssh, "SSH_ROUTES_DIR", routes)

    ssh.write_route(_workspace())

    assert "stale route" not in target.read_text()
    assert untouched.read_text() == "other route\n"


def test_remove_route_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routes = tmp_path / "workspaces"
    routes.mkdir()
    route = routes / _workspace().ssh_alias
    route.write_text("route\n")
    monkeypatch.setattr(ssh, "SSH_ROUTES_DIR", routes)

    ssh.remove_route(_workspace())
    ssh.remove_route(_workspace())

    assert not route.exists()
