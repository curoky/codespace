"""Tests for managed SSH assets and dynamic host projections."""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest

from controller import ssh
from controller.models import Environment, ssh_port
from controller.runtime.transport import SSHRoute


@pytest.fixture
def ssh_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / ".ssh"
    codespace_dir = root / "codespace"
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    config_asset = assets_dir / "config"
    config_asset.write_text(
        "Include ~/.ssh/codespace/hosts/*.conf\n\n"
        "Host codespace-*\n"
        "  HostName 127.0.0.1\n"
        "  User x\n"
        "  IdentityFile ~/.ssh/codespace/login_key\n"
        "  IdentitiesOnly yes\n"
        "  HostKeyAlias codespace\n"
        "  StrictHostKeyChecking yes\n"
        "  UserKnownHostsFile ~/.ssh/codespace/known_hosts/codespace\n",
        encoding="utf-8",
    )
    known_hosts_asset = assets_dir / "known_hosts"
    known_hosts_asset.write_text("codespace ssh-ed25519 HOST_KEY\n", encoding="utf-8")
    login_key_asset = assets_dir / "login_key"
    login_key_asset.write_text("PRIVATE\n", encoding="utf-8")
    monkeypatch.setattr(ssh, "SSH_CONFIG_PATH", root / "config")
    monkeypatch.setattr(ssh, "CODESPACE_DIR", codespace_dir)
    monkeypatch.setattr(ssh, "CODESPACE_CONFIG_PATH", codespace_dir / "config")
    monkeypatch.setattr(ssh, "HOSTS_DIR", codespace_dir / "hosts")
    monkeypatch.setattr(ssh, "KNOWN_HOSTS_DIR", codespace_dir / "known_hosts")
    monkeypatch.setattr(ssh, "KNOWN_HOSTS_PATH", codespace_dir / "known_hosts" / "codespace")
    monkeypatch.setattr(ssh, "LOGIN_KEY_PATH", codespace_dir / "login_key")
    monkeypatch.setattr(ssh, "SSH_CONFIG_ASSET", config_asset)
    monkeypatch.setattr(ssh, "KNOWN_HOSTS_ASSET", known_hosts_asset)
    monkeypatch.setattr(ssh, "LOGIN_KEY_ASSET", login_key_asset)
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
    managed = ssh_layout / "codespace"
    assert (managed / "config").read_text() == ssh.SSH_CONFIG_ASSET.read_text()
    known_hosts = ssh_layout / "codespace" / "known_hosts" / "codespace"
    assert known_hosts.read_text() == ssh.KNOWN_HOSTS_ASSET.read_text()
    login_key = managed / "login_key"
    assert login_key.read_text() == ssh.LOGIN_KEY_ASSET.read_text()
    assert stat.S_IMODE(login_key.stat().st_mode) == 0o600
    assert stat.S_IMODE(known_hosts.stat().st_mode) == 0o600
    assert stat.S_IMODE((managed / "config").stat().st_mode) == 0o600
    assert not (hosts / "deleted.conf").exists()
    assert (hosts / "home.conf").read_text() == "preserved until inventory"
    assert stat.S_IMODE(main.stat().st_mode) == 0o600


def test_initialize_does_not_replace_unchanged_config(ssh_layout: Path) -> None:
    ssh.initialize(["home"])
    main = ssh_layout / "config"
    managed = ssh_layout / "codespace"
    paths = (
        main,
        managed / "config",
        managed / "known_hosts" / "codespace",
        managed / "login_key",
    )
    inodes = tuple(path.stat().st_ino for path in paths)

    ssh.initialize(["home"])

    assert tuple(path.stat().st_ino for path in paths) == inodes


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
    assert "ProxyJump home" in content
    assert "HostName" not in content
    assert "IdentityFile" not in content
    managed_config = (ssh_layout / "codespace" / "config").read_text()
    assert "Host codespace-*" in managed_config
    assert "HostName 127.0.0.1" in managed_config
    assert "IdentityFile ~/.ssh/codespace/login_key" in managed_config
    assert "HostKeyAlias codespace" in managed_config
    assert "StrictHostKeyChecking yes" in managed_config
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_initialize_rejects_missing_asset(
    ssh_layout: Path,
) -> None:
    ssh.LOGIN_KEY_ASSET.unlink()

    with pytest.raises(RuntimeError, match="SSH asset is missing"):
        ssh.initialize(["home"])


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
    assert f"IdentityFile={ssh.LOGIN_KEY_PATH}" in command
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


def test_list_workspaces_reads_two_directory_levels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=("/home/x/codespace/devspace/debug\0/home/x/codespace/service-api/default\0"),
            stderr="",
        )

    monkeypatch.setattr(ssh.subprocess, "run", run)

    assert ssh.list_workspaces(_remote_route(), "/home/x/codespace") == [
        "/home/x/codespace/devspace/debug",
        "/home/x/codespace/service-api/default",
    ]
    assert "find /home/x/codespace" in commands[0][-1]
    assert "-mindepth 2 -maxdepth 2" in commands[0][-1]
    assert "-print0" in commands[0][-1]


def test_list_workspaces_rejects_path_outside_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ssh.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout="/home/x/other/devspace/debug\0",
            stderr="",
        ),
    )

    with pytest.raises(RuntimeError, match="outside"):
        ssh.list_workspaces(_remote_route(), "/home/x/codespace")


def test_read_host_environment_returns_only_requested_exported_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                "PATH=/usr/bin\0HTTP_PROXY=http://proxy:3128\0EMPTY=\0MULTILINE=line 1\nline 2\0"
            ),
            stderr="",
        )

    monkeypatch.setattr(ssh.subprocess, "run", run)

    environment = ssh.read_host_environment(
        _remote_route(),
        ["HTTP_PROXY", "EMPTY", "MULTILINE"],
    )

    assert environment == {
        "HTTP_PROXY": "http://proxy:3128",
        "EMPTY": "",
        "MULTILINE": "line 1\nline 2",
    }
    assert commands[0][-2:] == ["home", "env -0"]


def test_read_host_environment_rejects_missing_export(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ssh.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout="HTTP_PROXY=http://proxy:3128\0",
            stderr="",
        ),
    )

    with pytest.raises(RuntimeError, match=r"does not export.*\['NO_PROXY'\]"):
        ssh.read_host_environment(_remote_route(), ["HTTP_PROXY", "NO_PROXY"])


def test_read_host_environment_rejects_podman_machine() -> None:
    route = SSHRoute(host="local", machine="podman-machine-default")

    with pytest.raises(RuntimeError, match="not supported for Podman Machine"):
        ssh.read_host_environment(route, ["HTTP_PROXY"])


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
