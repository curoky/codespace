"""Tests for Workspace SSH routes and authenticated Host forwarding."""

from __future__ import annotations

import shutil
import stat
import subprocess
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


@pytest.mark.parametrize("internal", [False, True])
def test_macos_contract_resolves_persisted_routes_and_authenticated_tunnels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    internal: bool,
) -> None:
    source = (
        Path(__file__).resolve().parents[2] / "platform/macos/rootfs/Users/x/.ssh/codespace/config"
    )
    config = tmp_path / "config"
    routes = tmp_path / "routes"
    config.write_text(source.read_text().replace("~/.ssh/codespace/workspaces/*", f"{routes}/*"))
    monkeypatch.setattr(ssh, "SSH_CONFIG_PATH", config)
    monkeypatch.setattr(ssh, "SSH_ROUTES_DIR", routes)
    workspace = _workspace()
    if internal:
        options = ssh.connection_options(
            workspace, SSHRoute(host="home", control_path=Path("/tmp/host.sock"))
        )
    else:
        ssh.write_route(workspace)
        options = ["-F", str(config)]

    ssh_binary = shutil.which("ssh")
    assert ssh_binary is not None
    result = subprocess.run(  # noqa: S603 - parse repository config without connecting
        [ssh_binary, "-G", *options, workspace.ssh_alias],
        check=True,
        capture_output=True,
        text=True,
    )
    resolved = dict(line.split(" ", 1) for line in result.stdout.splitlines())
    assert resolved["hostname"] == "127.0.0.1"
    assert resolved["user"] == "x"
    assert resolved["port"] == str(workspace.ssh_host_port)
    assert resolved["hostkeyalias"] == "codespace"
    assert resolved["stricthostkeychecking"] == "true"
    assert resolved["batchmode"] == "yes"
    control = "-o ControlPath=/tmp/host.sock " if internal else ""
    assert resolved["proxycommand"] == f"ssh -o BatchMode=yes {control}-W %h:%p home"


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
