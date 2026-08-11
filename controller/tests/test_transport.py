"""Tests for reusable system-SSH Podman socket forwards."""

from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path

import pytest

from controller.config import HostConfig
from controller.transport import PodmanTransport


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


def test_transport_uses_system_ssh_command_and_private_runtime(tmp_path: Path) -> None:
    commands: list[list[str]] = []
    processes: list[FakeProcess] = []
    clients: list[FakeClient] = []

    def process_factory(command: list[str], **_kwargs: object) -> FakeProcess:
        commands.append(command)
        socket_path = Path(command[-2].split(":", 1)[0])
        socket_path.touch()
        process = FakeProcess()
        processes.append(process)
        return process

    def client_factory(*, base_url: str, timeout: float | None = None) -> FakeClient:
        client = FakeClient(base_url, timeout)
        clients.append(client)
        return client

    transport = PodmanTransport(
        {"home": HostConfig()},
        runtime_parent=tmp_path,
        process_factory=process_factory,
        client_factory=client_factory,  # type: ignore[arg-type]
    )

    returned = transport.client("home")

    assert commands == [
        [
            "ssh",
            "-N",
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "StreamLocalBindUnlink=yes",
            "-o",
            "ServerAliveInterval=15",
            "-o",
            "ServerAliveCountMax=3",
            "-L",
            f"{transport.runtime_dir}/home.sock:/run/podman/podman.sock",
            "home",
        ]
    ]
    assert "StrictHostKeyChecking=no" not in commands[0]
    assert returned is clients[0]
    assert clients[0].base_url == f"unix://{transport.runtime_dir}/home.sock"
    assert clients[0].timeout == 60.0
    assert stat.S_IMODE(transport.runtime_dir.stat().st_mode) == 0o700

    transport.close()

    assert processes[0].terminated is True
    assert clients[0].closed is True
    assert not transport.runtime_dir.exists()


def test_transport_reuses_live_tunnel_and_rebuilds_dead_tunnel(tmp_path: Path) -> None:
    processes: list[FakeProcess] = []
    clients: list[FakeClient] = []

    def process_factory(command: list[str], **_kwargs: object) -> FakeProcess:
        Path(command[-2].split(":", 1)[0]).touch()
        process = FakeProcess()
        processes.append(process)
        return process

    def client_factory(*, base_url: str, timeout: float | None = None) -> FakeClient:
        client = FakeClient(base_url, timeout)
        clients.append(client)
        return client

    transport = PodmanTransport(
        {"home": HostConfig()},
        runtime_parent=tmp_path,
        process_factory=process_factory,
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

    def process_factory(command: list[str], **_kwargs: object) -> FakeProcess:
        commands.append(command)
        Path(command[-2].split(":", 1)[0]).touch()
        return FakeProcess()

    def client_factory(*, base_url: str, timeout: float | None = None) -> FakeClient:
        return FakeClient(base_url, timeout)

    transport = PodmanTransport(
        {"boe": HostConfig(podman_socket="/tmp/podmanxd.sock")},
        runtime_parent=tmp_path,
        process_factory=process_factory,
        client_factory=client_factory,  # type: ignore[arg-type]
    )

    transport.client("boe")

    assert commands[0][-2] == f"{transport.runtime_dir}/boe.sock:/tmp/podmanxd.sock"

    transport.close()


def test_transport_connects_to_rootful_podman_machine_socket(tmp_path: Path) -> None:
    api_socket = tmp_path / "machine.sock"
    identity = tmp_path / "machine-key"
    api_socket.touch()
    identity.touch()
    commands: list[list[str]] = []
    clients: list[FakeClient] = []

    def run_factory(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        payload = [
            {
                "State": "running",
                "Rootful": True,
                "ConnectionInfo": {"PodmanSocket": {"Path": str(api_socket)}},
                "SSHConfig": {"Port": 54321, "IdentityPath": str(identity)},
            }
        ]
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    def client_factory(*, base_url: str, timeout: float | None = None) -> FakeClient:
        client = FakeClient(base_url, timeout)
        clients.append(client)
        return client

    transport = PodmanTransport(
        {
            "local": HostConfig(
                type="podman-machine",
                machine="podman-machine-default",
            )
        },
        runtime_parent=tmp_path,
        process_factory=lambda *args, **kwargs: pytest.fail("must not start SSH tunnel"),
        client_factory=client_factory,  # type: ignore[arg-type]
        run_factory=run_factory,
    )

    client = transport.client("local")
    route = transport.ssh_route("local")

    assert commands == [["podman", "machine", "inspect", "podman-machine-default"]]
    assert client is clients[0]
    assert clients[0].base_url == f"unix://{api_socket}"
    assert clients[0].timeout == 60.0
    assert route.host == "local"
    assert route.machine == "podman-machine-default"
    assert route.port == 54321
    assert route.identity_path == identity

    transport.close()
    assert clients[0].closed is True


def test_transport_rejects_rootless_podman_machine(tmp_path: Path) -> None:
    def run_factory(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        payload = [{"State": "running", "Rootful": False}]
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    transport = PodmanTransport(
        {
            "local": HostConfig(
                type="podman-machine",
                machine="podman-machine-default",
            )
        },
        runtime_parent=tmp_path,
        run_factory=run_factory,
    )

    with pytest.raises(RuntimeError, match="must use rootful mode"):
        transport.client("local")

    transport.close()
