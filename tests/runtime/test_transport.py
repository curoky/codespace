"""Tests for reusable system-SSH Podman socket forwards over one ControlMaster."""

from __future__ import annotations

import hashlib
import io
import os
import stat
import subprocess
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from codespace.runtime import transport as transport_module
from codespace.runtime.transport import PodmanTransport, TransportError


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
        {"home"},
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
    assert "ControlPersist=no" in command
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
        {host},
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
        {"home"},
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


def test_transport_serializes_master_startup_across_hosts(tmp_path: Path) -> None:
    first_factory_entered = Event()
    release_first_factory = Event()
    second_call_started = Event()
    second_factory_entered = Event()
    processes: list[FakeProcess] = []

    def process_factory(command: list[str], **_kwargs: object) -> FakeProcess:
        host = command[-1]
        if host == "first":
            first_factory_entered.set()
            assert release_first_factory.wait(timeout=2)
        else:
            second_factory_entered.set()
        control = next(token for token in command if token.startswith("ControlPath="))
        Path(control.split("=", 1)[1]).touch()
        process = FakeProcess()
        processes.append(process)
        return process

    transport = PodmanTransport(
        {"first", "second"},
        runtime_parent=tmp_path,
        process_factory=process_factory,
        client_factory=FakeClient,  # type: ignore[arg-type]
    )

    def connect_second() -> object:
        second_call_started.set()
        return transport.client("second")

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(transport.client, "first")
        first_started = first_factory_entered.wait(timeout=2)
        if not first_started:
            release_first_factory.set()
        assert first_started

        second = executor.submit(connect_second)
        second_started = second_call_started.wait(timeout=2)
        try:
            assert second_started
            assert not second_factory_entered.wait(timeout=0.1)
        finally:
            release_first_factory.set()

        first.result(timeout=2)
        second.result(timeout=2)

    assert second_factory_entered.is_set()
    transport.close()
    assert all(process.terminated for process in processes)


def test_transport_reuses_workspace_agent_forward(tmp_path: Path) -> None:
    processes: list[FakeProcess] = []
    forward_commands: list[list[str]] = []

    def run_factory(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        forward_commands.append(command)
        return _ok_run(command, **kwargs)

    transport = PodmanTransport(
        {"home"},
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


def test_tcp_forward_reuses_serializes_and_rebuilds_connections(tmp_path: Path) -> None:
    commands: list[list[str]] = []
    processes: list[FakeProcess] = []
    transport = PodmanTransport(
        {"home"},
        runtime_parent=tmp_path,
        process_factory=_master_factory(processes, commands),
    )

    def connect(connection_id: str = "container-1") -> int:
        return transport.forward_tcp(
            "home",
            "workspace",
            port=8005,
            options=["-F", "/tmp/workspace.conf", "-o", "Port=22000"],
            connection_id=connection_id,
        )

    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            ports = list(executor.map(lambda _: connect(), range(4)))
        assert len(set(ports)) == 1
        assert len(processes) == 1
        command = commands[0]
        assert command[-3:] == ["-L", f"127.0.0.1:{ports[0]}:127.0.0.1:8005", "workspace"]
        assert command[:2] == ["ssh", "-N"]
        assert "ControlPersist=no" in command
        assert "ExitOnForwardFailure=yes" in command
        assert "GatewayPorts=no" in command
        assert "BatchMode=yes" in command
        assert "/tmp/workspace.conf" in command
        assert "Port=22000" in command

        connect("container-2")
        assert processes[0].terminated
        assert len(processes) == 2

        processes[1].return_code = 255
        connect("container-2")
        assert len(processes) == 3

        transport.close_tcp("home", "workspace")
        assert processes[2].terminated
        transport.close_tcp("home", "workspace")
        connect("container-2")
    finally:
        transport.close()
    assert processes[-1].terminated
    assert not transport.runtime_dir.exists()
    with pytest.raises(TransportError, match="closed"):
        connect()


def test_tcp_forwards_isolate_ports_workspaces_and_hosts(tmp_path: Path) -> None:
    processes: list[FakeProcess] = []
    transport = PodmanTransport(
        {"home", "other"},
        runtime_parent=tmp_path,
        process_factory=_master_factory(processes),
    )
    try:
        for host, destination, port in [
            ("home", "first", 8005),
            ("home", "first", 8080),
            ("home", "second", 8005),
            ("other", "first", 8005),
        ]:
            transport.forward_tcp(host, destination, port=port, options=[], connection_id="c")
        assert len(processes) == 4
        assert not any(process.terminated for process in processes)
        transport.close_tcp("home", "first")
        assert all(process.terminated for process in processes[:2])
        assert not any(process.terminated for process in processes[2:])
    finally:
        transport.close()
    assert all(process.terminated for process in processes)


def test_tcp_forward_start_failure_is_not_cached(tmp_path: Path) -> None:
    processes: list[FakeProcess] = []

    def fail(command: list[str], **kwargs: object) -> FakeProcess:
        process = _master_factory(processes)(command, **kwargs)
        process.return_code = 255
        process.stderr = io.BytesIO(b"bind: Address already in use")  # type: ignore[assignment]
        return process

    transport = PodmanTransport({"home"}, runtime_parent=tmp_path, process_factory=fail)
    try:
        for _ in range(2):
            with pytest.raises(TransportError, match="Address already in use"):
                transport.forward_tcp("home", "workspace", port=8005, options=[], connection_id="c")
        assert len(processes) == 2
        assert not list(transport.runtime_dir.glob("tcp-*.sock"))
    finally:
        transport.close()


def test_tcp_forward_timeout_terminates_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    process = FakeProcess()
    monkeypatch.setattr(transport_module, "_START_TIMEOUT", 0)
    transport = PodmanTransport(
        {"home"},
        runtime_parent=tmp_path,
        process_factory=lambda *_args, **_kwargs: process,
    )
    try:
        with pytest.raises(TransportError, match="did not create control socket"):
            transport.forward_tcp("home", "workspace", port=8005, options=[], connection_id="c")
        assert process.terminated
    finally:
        transport.close()
