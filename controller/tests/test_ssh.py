"""Tests for managed SSH assets and dynamic host projections."""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest

from controller import ssh
from controller.models import Environment, ssh_port
from controller.transport import SSHRoute


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
        workspace="devspace",
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
def _clear_data_paths_cache() -> None:
    ssh.remote_data_paths.cache_clear()


def test_remote_data_paths_resolves_single_host_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="/home/x/codespace\n", stderr="")

    monkeypatch.setattr(ssh.subprocess, "run", run)

    paths = ssh.remote_data_paths(_remote_route())

    assert paths.root == "/home/x/codespace"
    assert paths.workspaces == "/home/x/codespace/workspaces"
    assert paths.deployments == "/home/x/codespace/deployments"
    assert commands[0][0] == "ssh"
    assert commands[0][-2] == "home"
    assert "mkdir -p" in commands[0][-1]
    assert '"$HOME/codespace/workspaces"' in commands[0][-1]
    assert '"$HOME/codespace/deployments"' in commands[0][-1]


def test_remote_data_paths_is_cached_per_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command[-2])
        return subprocess.CompletedProcess(command, 0, stdout="/home/x/codespace", stderr="")

    monkeypatch.setattr(ssh.subprocess, "run", run)

    first = ssh.remote_data_paths(_remote_route())
    second = ssh.remote_data_paths(_remote_route())

    assert first == second
    assert first.root == "/home/x/codespace"
    assert calls == ["home"]


def test_remote_root_rejects_non_absolute_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ssh.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command, 0, stdout="relative/path", stderr=""
        ),
    )

    with pytest.raises(RuntimeError, match="non-absolute codespace data root"):
        ssh.remote_data_paths(_remote_route())


def test_remote_root_wraps_ssh_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def run(command: list[str], **_kwargs: object) -> None:
        raise subprocess.CalledProcessError(255, command, stderr="permission denied")

    monkeypatch.setattr(ssh.subprocess, "run", run)

    with pytest.raises(RuntimeError, match="failed to resolve codespace data root"):
        ssh.remote_data_paths(_remote_route())


def test_prepare_workspace_creates_directory_as_login_user_over_ssh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(ssh.subprocess, "run", run)

    path = "/home/x/codespace/workspaces/devspace/debug/workspace"
    ssh.prepare_directories(_remote_route(), [path])

    command = commands[0]
    assert command[0] == "ssh"
    assert command[-2] == "home"
    assert command[-1] == f"mkdir -p -- {path}"


def test_prepare_workspace_rejects_non_absolute_target() -> None:
    with pytest.raises(RuntimeError, match="non-absolute path"):
        ssh.prepare_directories(_remote_route(), ["relative/path"])


def test_prepare_workspace_wraps_ssh_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def run(command: list[str], **_kwargs: object) -> None:
        raise subprocess.CalledProcessError(1, command, stderr="permission denied")

    monkeypatch.setattr(ssh.subprocess, "run", run)

    with pytest.raises(RuntimeError, match="failed to prepare directories"):
        ssh.prepare_directories(
            _remote_route(),
            ["/home/x/codespace/workspaces/devspace/debug/workspace"],
        )


def test_reset_control_state_removes_stale_runtime_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(ssh.subprocess, "run", run)
    control = "/home/x/codespace/workspaces/devspace/debug/control"

    ssh.reset_control_state(_remote_route(), control)

    command, kwargs = calls[0]
    assert command[-2] == "home"
    assert f"chmod 0700 -- {control}" in command[-1]
    assert f"rm -f -- {control}/agent.sock" in command[-1]
    assert f"{control}/provider-ready" in command[-1]
    assert kwargs["stdin"] == subprocess.DEVNULL


def test_reset_control_state_rejects_relative_path() -> None:
    with pytest.raises(RuntimeError, match="non-absolute control path"):
        ssh.reset_control_state(_remote_route(), "relative/control")


def test_signal_provider_ready_creates_private_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(ssh.subprocess, "run", run)
    control = "/home/x/codespace/workspaces/devspace/debug/control"

    ssh.signal_provider_ready(_remote_route(), control)

    assert f"umask 077; : >{control}/provider-ready" in calls[0][-1]


def test_list_instances_reads_two_directory_levels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                "/home/x/codespace/workspaces/devspace/debug\0"
                "/home/x/codespace/workspaces/service-api/default\0"
            ),
            stderr="",
        )

    monkeypatch.setattr(ssh.subprocess, "run", run)

    assert ssh.list_instances(_remote_route(), "/home/x/codespace/workspaces") == [
        "/home/x/codespace/workspaces/devspace/debug",
        "/home/x/codespace/workspaces/service-api/default",
    ]
    assert "find /home/x/codespace/workspaces" in commands[0][-1]
    assert "-mindepth 2 -maxdepth 2" in commands[0][-1]
    assert "-print0" in commands[0][-1]


def test_list_instances_rejects_path_outside_root(
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
        ssh.list_instances(_remote_route(), "/home/x/codespace/workspaces")


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
