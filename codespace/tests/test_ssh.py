"""Tests for generated SSH projections and the global login key."""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest

from codespace import ssh
from codespace.models import Environment, ssh_port


@pytest.fixture
def ssh_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / ".ssh"
    codespace_dir = root / "codespace"
    monkeypatch.setattr(ssh, "SSH_CONFIG_PATH", root / "config")
    monkeypatch.setattr(ssh, "CODESPACE_DIR", codespace_dir)
    monkeypatch.setattr(ssh, "CODESPACE_CONFIG_PATH", codespace_dir / "config")
    monkeypatch.setattr(ssh, "HOSTS_DIR", codespace_dir / "hosts")
    monkeypatch.setattr(ssh, "KNOWN_HOSTS_DIR", codespace_dir / "known_hosts")
    monkeypatch.setattr(ssh, "LOGIN_KEY_PATH", codespace_dir / "id_ed25519")
    return root


def _environment(instance: str = "debug") -> Environment:
    identity = f"codespace-home-devspace-{instance}"
    return Environment(
        id=identity,
        host="home",
        project="devspace",
        instance=instance,
        repo="curoky/devspace",
        provider="github",
        image="image:latest",
        ssh_port=ssh_port(identity),
        container_id=f"container-{instance}",
        status="running",
    )


def test_initialize_generates_include_layout_and_removes_deleted_hosts(
    ssh_layout: Path,
) -> None:
    main = ssh_layout / "config"
    hosts = ssh_layout / "codespace" / "hosts"
    main.parent.mkdir(parents=True)
    main.write_text(
        "Host existing\n    HostName example.org\nInclude ~/.ssh/codespace/config\n",
        encoding="utf-8",
    )
    hosts.mkdir(parents=True)
    (hosts / "deleted.conf").write_text("stale", encoding="utf-8")
    (hosts / "home.conf").write_text("preserved until inventory", encoding="utf-8")

    ssh.initialize(["home"])

    content = main.read_text(encoding="utf-8")
    assert content.count(ssh.INCLUDE_LINE) == 1
    assert content.startswith(f"{ssh.INCLUDE_LINE}\n\n")
    assert "Host existing" in content
    assert (ssh_layout / "codespace" / "config").read_text() == (
        "Include ~/.ssh/codespace/hosts/*.conf\n"
    )
    assert not (hosts / "deleted.conf").exists()
    assert (hosts / "home.conf").read_text() == "preserved until inventory"
    assert stat.S_IMODE(main.stat().st_mode) == 0o600


def test_write_host_replaces_complete_projection(ssh_layout: Path) -> None:
    ssh.initialize(["home"])
    path = ssh_layout / "codespace" / "hosts" / "home.conf"
    path.write_text("old block\n", encoding="utf-8")

    ssh.write_host("home", [_environment("debug"), _environment("default")])

    content = path.read_text(encoding="utf-8")
    assert "old block" not in content
    assert content.count("Host codespace-home-devspace-") == 2
    assert "HostName 127.0.0.1" in content
    assert "ProxyJump home" in content
    assert "User x" in content
    assert "IdentityFile ~/.ssh/codespace/id_ed25519" in content
    assert (
        "UserKnownHostsFile ~/.ssh/codespace/known_hosts/codespace-home-devspace-debug"
    ) in content
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_ensure_login_key_generates_once(
    ssh_layout: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> object:
        calls.append(command)
        key_path = Path(command[command.index("-f") + 1])
        if "-t" in command:
            key_path.write_text("PRIVATE", encoding="utf-8")
            return object()
        return type("Result", (), {"stdout": "ssh-ed25519 PUBLIC\n"})()

    monkeypatch.setattr(ssh.subprocess, "run", run)

    first = ssh.ensure_login_key()
    second = ssh.ensure_login_key()

    assert first == second == "ssh-ed25519 PUBLIC"
    assert len(calls) == 2
    assert stat.S_IMODE((ssh_layout / "codespace" / "id_ed25519").stat().st_mode) == 0o600


def test_probe_uses_proxyjump_and_environment_alias(
    ssh_layout: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(
        ssh.subprocess,
        "run",
        lambda command, **_kwargs: commands.append(command),
    )

    ssh.probe(_environment())

    command = commands[0]
    assert "ProxyJump=home" in command
    assert "HostName=127.0.0.1" in command
    assert f"IdentityFile={ssh_layout}/codespace/id_ed25519" in command
    assert command[-2:] == ["codespace-home-devspace-debug", "true"]


def test_probe_retries_until_ssh_login_succeeds(
    ssh_layout: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = iter(
        [
            subprocess.CalledProcessError(255, ["ssh"], stderr=b"connection refused"),
            None,
        ]
    )
    sleeps: list[float] = []

    def run(command: list[str], **_kwargs: object) -> None:
        result = next(attempts)
        if result is not None:
            raise result

    monkeypatch.setattr(ssh.subprocess, "run", run)
    monkeypatch.setattr(ssh.time, "sleep", lambda interval: sleeps.append(interval))

    ssh.probe(_environment())

    assert sleeps == [0.5]
