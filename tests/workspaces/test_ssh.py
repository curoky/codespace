"""Tests for managed SSH assets and Workspace projections."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from codespace.runtime.transport import SSHRoute
from codespace.workspaces import ssh
from codespace.workspaces.models import Workspace, workspace_ssh_port


@pytest.fixture
def ssh_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / ".ssh"
    managed = root / "codespace"
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "config").write_text("Host codespace-workspace-*\n", encoding="utf-8")
    (assets / "known_hosts").write_text("codespace ssh-ed25519 KEY\n", encoding="utf-8")
    (assets / "login_key").write_text("PRIVATE\n", encoding="utf-8")
    monkeypatch.setattr(ssh, "SSH_CONFIG_PATH", root / "config")
    monkeypatch.setattr(ssh, "CODESPACE_DIR", managed)
    monkeypatch.setattr(ssh, "CODESPACE_CONFIG_PATH", managed / "config")
    monkeypatch.setattr(ssh, "HOSTS_DIR", managed / "hosts")
    monkeypatch.setattr(ssh, "KNOWN_HOSTS_DIR", managed / "known_hosts")
    monkeypatch.setattr(ssh, "KNOWN_HOSTS_PATH", managed / "known_hosts/codespace")
    monkeypatch.setattr(ssh, "LOGIN_KEY_PATH", managed / "login_key")
    monkeypatch.setattr(ssh, "SSH_CONFIG_ASSET", assets / "config")
    monkeypatch.setattr(ssh, "KNOWN_HOSTS_ASSET", assets / "known_hosts")
    monkeypatch.setattr(ssh, "LOGIN_KEY_ASSET", assets / "login_key")
    return root


def _workspace(name: str = "debug") -> Workspace:
    identity = f"codespace-workspace-home-codespace-{name}"
    return Workspace(
        id=identity,
        project="codespace",
        workspace=name,
        host="home",
        source="github",
        repository="curoky/codespace",
        image="workspace:latest",
        platform="native",
        ssh_port=workspace_ssh_port(identity),
        container_id=f"container-{name}",
        status="running",
    )


def test_initialize_writes_private_assets_and_removes_unknown_hosts(ssh_layout: Path) -> None:
    hosts = ssh_layout / "codespace/hosts"
    hosts.mkdir(parents=True)
    (hosts / "removed.conf").write_text("stale", encoding="utf-8")

    ssh.initialize(["home"])

    assert (ssh_layout / "config").read_text().startswith(ssh.INCLUDE_LINE)
    assert not (hosts / "removed.conf").exists()
    assert stat.S_IMODE((ssh_layout / "codespace/login_key").stat().st_mode) == 0o600


def test_write_host_replaces_complete_projection(ssh_layout: Path) -> None:
    ssh.initialize(["home"])

    ssh.write_host(
        "home",
        [_workspace("debug"), _workspace("default")],
        SSHRoute(host="home"),
    )

    content = (ssh_layout / "codespace/hosts/home.conf").read_text()
    assert content.count("Host codespace-workspace-home-codespace-") == 2
    assert "ProxyJump home" in content


def test_probe_keeps_host_key_verification(
    ssh_layout: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(
        ssh.subprocess,
        "run",
        lambda command, **_kwargs: commands.append(command),
    )

    ssh.probe(_workspace(), SSHRoute(host="home"))

    command = commands[0]
    assert "StrictHostKeyChecking=yes" in command
    assert "ProxyJump=home" in command
    assert command[-2:] == ["codespace-workspace-home-codespace-debug", "true"]
