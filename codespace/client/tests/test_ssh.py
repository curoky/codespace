"""Tests for generated SSH projections and the global login key."""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest

from codespace.client import ssh
from codespace.client.models import Environment, ssh_port
from codespace.client.transport import SSHRoute


@pytest.fixture
def ssh_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / ".ssh"
    codespace_dir = root / "codespace"
    monkeypatch.setattr(ssh, "SSH_CONFIG_PATH", root / "config")
    monkeypatch.setattr(ssh, "CODESPACE_DIR", codespace_dir)
    monkeypatch.setattr(ssh, "CODESPACE_CONFIG_PATH", codespace_dir / "config")
    monkeypatch.setattr(ssh, "HOSTS_DIR", codespace_dir / "hosts")
    monkeypatch.setattr(ssh, "KNOWN_HOSTS_DIR", codespace_dir / "known_hosts")
    monkeypatch.setattr(ssh, "KNOWN_HOSTS_PATH", codespace_dir / "known_hosts" / "codespace")
    monkeypatch.setattr(ssh, "LOGIN_KEY_PATH", codespace_dir / "id_ed25519")
    return root


def _environment(instance: str = "debug") -> Environment:
    identity = f"codespace-home-devspace-{instance}"
    return Environment(
        id=identity,
        host="home",
        project="devspace",
        instance=instance,
        type="repo",
        repo="curoky/devspace",
        provider="github",
        image="image:latest",
        platform="native",
        ssh_port=ssh_port(identity),
        container_id=f"container-{instance}",
        status="running",
    )


def _remote_route() -> SSHRoute:
    return SSHRoute(host="home")


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
    known_hosts = ssh_layout / "codespace" / "known_hosts" / "codespace"
    assert known_hosts.read_text() == f"codespace {ssh.IMAGE_HOST_KEY}\n"
    assert stat.S_IMODE(known_hosts.stat().st_mode) == 0o600
    assert not (hosts / "deleted.conf").exists()
    assert (hosts / "home.conf").read_text() == "preserved until inventory"
    assert stat.S_IMODE(main.stat().st_mode) == 0o600


def test_initialize_does_not_replace_unchanged_config(ssh_layout: Path) -> None:
    ssh.initialize(["home"])
    main = ssh_layout / "config"
    managed = ssh_layout / "codespace" / "config"
    inodes = (main.stat().st_ino, managed.stat().st_ino)

    ssh.initialize(["home"])

    assert (main.stat().st_ino, managed.stat().st_ino) == inodes


def test_write_host_replaces_complete_projection(ssh_layout: Path) -> None:
    ssh.initialize(["home"])
    path = ssh_layout / "codespace" / "hosts" / "home.conf"
    path.write_text("old block\n", encoding="utf-8")

    ssh.write_host(
        "home",
        [_environment("debug"), _environment("default")],
        _remote_route(),
    )

    content = path.read_text(encoding="utf-8")
    assert "old block" not in content
    assert content.count("Host codespace-home-devspace-") == 2
    assert "HostName 127.0.0.1" in content
    assert "ProxyJump home" in content
    assert "User x" in content
    assert "IdentityFile ~/.ssh/codespace/id_ed25519" in content
    assert "HostKeyAlias codespace" in content
    assert "StrictHostKeyChecking yes" in content
    assert "UserKnownHostsFile ~/.ssh/codespace/known_hosts/codespace" in content
    assert "known_hosts/codespace-home-devspace-debug" not in content
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

    ssh.probe(_environment(), _remote_route())

    command = commands[0]
    assert "ProxyJump=home" in command
    assert "HostName=127.0.0.1" in command
    assert f"IdentityFile={ssh_layout}/codespace/id_ed25519" in command
    assert "HostKeyAlias=codespace" in command
    assert "StrictHostKeyChecking=yes" in command
    assert f"UserKnownHostsFile={ssh_layout}/codespace/known_hosts/codespace" in command
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

    ssh.probe(_environment(), _remote_route())

    assert sleeps == [0.5]


@pytest.fixture(autouse=True)
def _clear_workspace_root_cache() -> None:
    ssh.remote_workspace_root.cache_clear()


def test_remote_workspace_root_resolves_home_and_creates_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="/home/x/codespace\n", stderr="")

    monkeypatch.setattr(ssh.subprocess, "run", run)

    root = ssh.remote_workspace_root(_remote_route())

    assert root == "/home/x/codespace"
    assert commands[0][0] == "ssh"
    assert commands[0][-2] == "home"
    # The remote command both creates the directory and prints the absolute path.
    assert "mkdir -p" in commands[0][-1]
    assert "codespace" in commands[0][-1]


def test_remote_workspace_root_is_cached_per_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command[-2])
        return subprocess.CompletedProcess(command, 0, stdout="/home/x/codespace", stderr="")

    monkeypatch.setattr(ssh.subprocess, "run", run)

    first = ssh.remote_workspace_root(_remote_route())
    second = ssh.remote_workspace_root(_remote_route())

    assert first == second == "/home/x/codespace"
    assert calls == ["home"]


def test_remote_workspace_root_rejects_non_absolute_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ssh.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command, 0, stdout="relative/path", stderr=""
        ),
    )

    with pytest.raises(RuntimeError, match="non-absolute workspace root"):
        ssh.remote_workspace_root(_remote_route())


def test_remote_workspace_root_wraps_ssh_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def run(command: list[str], **_kwargs: object) -> None:
        raise subprocess.CalledProcessError(255, command, stderr="permission denied")

    monkeypatch.setattr(ssh.subprocess, "run", run)

    with pytest.raises(RuntimeError, match="failed to resolve workspace root"):
        ssh.remote_workspace_root(_remote_route())


def test_prepare_workspace_creates_directory_as_login_user_over_ssh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(ssh.subprocess, "run", run)

    ssh.prepare_workspace(_remote_route(), "/home/x/codespace/devspace/debug")

    command = commands[0]
    assert command[0] == "ssh"
    assert command[-2] == "home"
    assert command[-1] == "mkdir -p -- /home/x/codespace/devspace/debug"


def test_prepare_workspace_rejects_non_absolute_target() -> None:
    with pytest.raises(RuntimeError, match="non-absolute workspace path"):
        ssh.prepare_workspace(_remote_route(), "relative/path")


def test_prepare_workspace_wraps_ssh_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def run(command: list[str], **_kwargs: object) -> None:
        raise subprocess.CalledProcessError(1, command, stderr="permission denied")

    monkeypatch.setattr(ssh.subprocess, "run", run)

    with pytest.raises(RuntimeError, match="failed to prepare workspace"):
        ssh.prepare_workspace(_remote_route(), "/home/x/codespace/devspace/debug")


def test_podman_machine_workspace_uses_root_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = tmp_path / "machine-key"
    identity.touch()
    route = SSHRoute(
        host="local",
        machine="podman-machine-default",
        port=54321,
        identity_path=identity,
    )
    commands: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        stdout = "/root/codespace" if "printf %s" in command[-1] else ""
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(ssh.subprocess, "run", run)

    root = ssh.remote_workspace_root(route)
    ssh.prepare_workspace(route, f"{root}/devspace/debug")

    assert root == "/root/codespace"
    for command in commands:
        assert "-i" in command
        assert str(identity) in command
        assert "-p" in command
        assert "54321" in command
        assert "StrictHostKeyChecking=accept-new" in command
        assert any(option.endswith("/known_hosts/machine-local") for option in command)
        assert command[-2] == "root@127.0.0.1"
    assert commands[1][-1] == "mkdir -p -- /root/codespace/devspace/debug"


def test_podman_machine_projection_and_probe_use_dedicated_proxy_command(
    ssh_layout: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = tmp_path / "machine-key"
    identity.touch()
    route = SSHRoute(
        host="home",
        machine="podman-machine-default",
        port=54321,
        identity_path=identity,
    )
    commands: list[list[str]] = []
    monkeypatch.setattr(
        ssh.subprocess,
        "run",
        lambda command, **_kwargs: commands.append(command),
    )
    ssh.initialize(["home"])

    ssh.write_host("home", [_environment()], route)
    ssh.probe(_environment(), route)

    projection = (ssh_layout / "codespace" / "hosts" / "home.conf").read_text(encoding="utf-8")
    assert "ProxyCommand ssh" in projection
    assert str(identity) in projection
    assert "-p 54321" in projection
    assert "root@127.0.0.1" in projection
    assert any(option.startswith("ProxyCommand=ssh") for option in commands[0])
