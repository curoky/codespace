"""Tests for reusable system-SSH Podman socket forwards over one ControlMaster."""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from collections.abc import Callable
from pathlib import Path

from codespace.runtime.transport import HostEndpoint, PodmanTransport


class FakeProcess:
    def __init__(self) -> None:
        self.return_code: int | None = None
        self.terminated = False
        self.killed = False
        self.stderr = None

    def poll(self) -> int | None:
        return self.return_code

    def terminate(self) -> None:
        self.terminated = True
        self.return_code = 0

    def kill(self) -> None:
        self.killed = True
        self.return_code = -9

    def wait(self, timeout: float) -> int:
        assert timeout == 2
        return self.return_code or 0


class FakeClient:
    def __init__(self, base_url: str, timeout: float | None = None) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _master_factory(
    processes: list[FakeProcess],
    commands: list[list[str]] | None = None,
) -> Callable[..., FakeProcess]:
    """Return a process factory that fakes a live master by creating its control socket."""

    def process_factory(command: list[str], **_kwargs: object) -> FakeProcess:
        if commands is not None:
            commands.append(command)
        # ControlPath option carries the control socket; create it so the master looks live.
        control = next(t for t in command if t.startswith("ControlPath="))
        Path(control.split("=", 1)[1]).touch()
        process = FakeProcess()
        processes.append(process)
        return process

    return process_factory


def _ok_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
    # ``ssh -O forward`` creates the local socket; emulate that side effect.
    socket_path = Path(command[command.index("-L") + 1].split(":", 1)[0])
    socket_path.touch()
    return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")


def test_transport_uses_control_master_and_private_runtime(tmp_path: Path) -> None:
    commands: list[list[str]] = []
    processes: list[FakeProcess] = []
    clients: list[FakeClient] = []

    def client_factory(*, base_url: str, timeout: float | None = None) -> FakeClient:
        client = FakeClient(base_url, timeout)
        clients.append(client)
        return client

    transport = PodmanTransport(
        {"home": HostEndpoint()},
        runtime_parent=tmp_path,
        process_factory=_master_factory(processes, commands),
        client_factory=client_factory,  # type: ignore[arg-type]
    )

    returned = transport.client("home")

    command = commands[0]
    digest = hashlib.sha256(b"home").hexdigest()[:16]
    control_path = transport.runtime_dir / f"control-{digest}.sock"
    podman_socket_path = transport.runtime_dir / f"podman-{digest}.sock"
    assert command[:2] == ["ssh", "-N"]
    assert "BatchMode=yes" in command
    assert f"ControlPath={control_path}" in command
    assert "ControlMaster=yes" in command
    assert command[-3:] == [
        "-L",
        f"{podman_socket_path}:/run/podman/podman.sock",
        "home",
    ]
    assert "StrictHostKeyChecking=no" not in command
    assert returned is clients[0]
    assert clients[0].base_url == f"unix://{podman_socket_path}"
    assert clients[0].timeout == 60.0
    assert stat.S_IMODE(transport.runtime_dir.stat().st_mode) == 0o700

    transport.close()

    assert processes[0].terminated is True
    assert clients[0].closed is True
    assert not transport.runtime_dir.exists()


def test_transport_default_socket_paths_fit_macos_limit() -> None:
    commands: list[list[str]] = []
    host = "h" * 63
    transport = PodmanTransport(
        {host: HostEndpoint()},
        process_factory=_master_factory([], commands),
        client_factory=FakeClient,  # type: ignore[arg-type]
    )

    try:
        transport.client(host)

        command = commands[0]
        control_option = next(value for value in command if value.startswith("ControlPath="))
        control_path = control_option.split("=", 1)[1]
        podman_socket_path = command[command.index("-L") + 1].split(":", 1)[0]
        assert transport.runtime_dir.parent == Path("/tmp")
        # OpenSSH binds through ``<ControlPath>.<16 random chars>``.
        assert len(os.fsencode(f"{control_path}.{'x' * 16}")) < 104
        assert len(os.fsencode(podman_socket_path)) < 104
        assert host not in control_path
        assert host not in podman_socket_path
    finally:
        transport.close()


def test_transport_reuses_live_master_and_rebuilds_dead_master(tmp_path: Path) -> None:
    processes: list[FakeProcess] = []
    clients: list[FakeClient] = []

    def client_factory(*, base_url: str, timeout: float | None = None) -> FakeClient:
        client = FakeClient(base_url, timeout)
        clients.append(client)
        return client

    transport = PodmanTransport(
        {"home": HostEndpoint()},
        runtime_parent=tmp_path,
        process_factory=_master_factory(processes),
        client_factory=client_factory,  # type: ignore[arg-type]
    )

    first = transport.client("home")
    second = transport.client("home")
    assert len(processes) == 1
    assert first is second

    processes[0].return_code = 255
    third = transport.client("home")
    assert len(processes) == 2
    assert third is not first
    assert clients[0].closed is True

    transport.close()
    assert clients[1].closed is True


def test_transport_forwards_per_host_remote_socket(tmp_path: Path) -> None:
    commands: list[list[str]] = []

    transport = PodmanTransport(
        {"boe": HostEndpoint(podman_socket="/tmp/podmanxd.sock")},
        runtime_parent=tmp_path,
        process_factory=_master_factory([], commands),
        client_factory=FakeClient,  # type: ignore[arg-type]
    )

    transport.client("boe")

    digest = hashlib.sha256(b"boe").hexdigest()[:16]
    assert commands[0][-2] == (f"{transport.runtime_dir}/podman-{digest}.sock:/tmp/podmanxd.sock")

    transport.close()


def test_transport_reuses_workspace_agent_forward(tmp_path: Path) -> None:
    processes: list[FakeProcess] = []
    forward_commands: list[list[str]] = []

    def run_factory(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        forward_commands.append(command)
        return _ok_run(command, **kwargs)

    transport = PodmanTransport(
        {"home": HostEndpoint()},
        runtime_parent=tmp_path,
        process_factory=_master_factory(processes),
        client_factory=FakeClient,  # type: ignore[arg-type]
        run_factory=run_factory,
    )
    transport.client("home")
    remote_socket = "/home/x/codespace/workspaces/codespace/debug/control/agent.sock"

    first = transport.forward_socket("home", remote_socket)
    second = transport.forward_socket("home", remote_socket)

    assert first == second
    assert first.name.startswith("agent-")
    # Only one ``ssh -O forward`` runs; the second call reuses the live forward.
    assert len(forward_commands) == 1
    command = forward_commands[0]
    assert command[:3] == ["ssh", "-O", "forward"]
    assert command[-2] == f"{first}:{remote_socket}"

    transport.close()
    assert processes[0].terminated is True
