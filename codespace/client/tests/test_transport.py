"""Tests for reusable system-SSH Podman socket forwards."""

from __future__ import annotations

import stat
from pathlib import Path

from codespace.client.transport import PodmanTransport


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
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
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

    def client_factory(*, base_url: str) -> FakeClient:
        client = FakeClient(base_url)
        clients.append(client)
        return client

    transport = PodmanTransport(
        ["home"],
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
            "-L",
            f"{transport.runtime_dir}/home.sock:/run/podman/podman.sock",
            "home",
        ]
    ]
    assert "StrictHostKeyChecking=no" not in commands[0]
    assert returned is clients[0]
    assert clients[0].base_url == f"unix://{transport.runtime_dir}/home.sock"
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

    def client_factory(*, base_url: str) -> FakeClient:
        client = FakeClient(base_url)
        clients.append(client)
        return client

    transport = PodmanTransport(
        ["home"],
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
