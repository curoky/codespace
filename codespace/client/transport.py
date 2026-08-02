"""Podman clients and SSH routes for remote hosts and local Podman machines."""

from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from podman import PodmanClient

from codespace.client.config import HostConfig

_START_TIMEOUT = 10.0
_START_INTERVAL = 0.05
# Cap every Podman call so a half-dead tunnel fails fast instead of hanging a
# create operation forever. Image pulls stream, so this bounds inter-chunk gaps
# rather than the whole download.
_CLIENT_TIMEOUT = 60.0
# Let SSH drop a silently-broken forward on its own; the dead process then fails
# is_running() and the next client() call rebuilds the tunnel.
_SERVER_ALIVE_INTERVAL = 15
_SERVER_ALIVE_COUNT_MAX = 3


class TransportError(RuntimeError):
    """Raised when a configured host cannot expose Podman or an SSH route."""


@dataclass(frozen=True, slots=True)
class SSHRoute:
    """Information needed to execute commands and proxy SSH through one host."""

    host: str
    machine: str | None = None
    port: int | None = None
    identity_path: Path | None = None

    @property
    def is_machine(self) -> bool:
        return self.machine is not None


@dataclass(slots=True)
class _Connection:
    socket_path: Path
    client: PodmanClient
    route: SSHRoute
    process: subprocess.Popen[bytes] | None = None

    def is_running(self) -> bool:
        return self.socket_path.exists() and (self.process is None or self.process.poll() is None)


ProcessFactory = Callable[..., subprocess.Popen[bytes]]
ClientFactory = Callable[..., PodmanClient]
RunFactory = Callable[..., subprocess.CompletedProcess[str]]


class PodmanTransport:
    """Reuse one Podman connection per configured SSH host or local machine."""

    def __init__(
        self,
        hosts: Mapping[str, HostConfig],
        *,
        runtime_parent: Path | None = None,
        process_factory: ProcessFactory = subprocess.Popen,
        client_factory: ClientFactory = PodmanClient,
        run_factory: RunFactory = subprocess.run,
    ) -> None:
        self._hosts = dict(hosts)
        self._runtime_dir = Path(tempfile.mkdtemp(prefix="codespace-", dir=runtime_parent))
        self._runtime_dir.chmod(0o700)
        self._process_factory = process_factory
        self._client_factory = client_factory
        self._run_factory = run_factory
        self._connections: dict[str, _Connection] = {}
        self._locks = {host: Lock() for host in hosts}
        self._closed = False

    @property
    def runtime_dir(self) -> Path:
        return self._runtime_dir

    def client(self, host: str) -> PodmanClient:
        """Return a Podman client connected to one live configured host."""
        if self._closed:
            raise TransportError("Podman transport is closed")
        if host not in self._hosts:
            raise TransportError(f"unknown host: {host}")
        return self._connection(host).client

    def ssh_route(self, host: str) -> SSHRoute:
        """Return the SSH route paired with one live Podman connection."""
        if self._closed:
            raise TransportError("Podman transport is closed")
        if host not in self._hosts:
            raise TransportError(f"unknown host: {host}")
        return self._connection(host).route

    def close(self) -> None:
        """Close Podman clients, SSH children, and the runtime directory."""
        if self._closed:
            return
        self._closed = True
        connections = list(self._connections.values())
        self._connections.clear()
        for connection in connections:
            connection.client.close()
            if connection.process is not None:
                self._stop(connection.process)
        shutil.rmtree(self._runtime_dir, ignore_errors=True)

    def _connection(self, host: str) -> _Connection:
        lock = self._locks[host]
        with lock:
            connection = self._connections.get(host)
            if connection is not None and connection.is_running():
                return connection
            if connection is not None:
                connection.client.close()
                if connection.process is not None:
                    self._stop(connection.process)
                    connection.socket_path.unlink(missing_ok=True)
            options = self._hosts[host]
            if options.type == "podman-machine":
                connection = self._connect_machine(host, options)
            else:
                connection = self._start_tunnel(host, options)
            self._connections[host] = connection
            return connection

    def _start_tunnel(self, host: str, options: HostConfig) -> _Connection:
        socket_path = self._runtime_dir / f"{host}.sock"
        socket_path.unlink(missing_ok=True)
        remote_socket = options.resolved_podman_socket()
        command = [
            "ssh",
            "-N",
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "StreamLocalBindUnlink=yes",
            "-o",
            f"ServerAliveInterval={_SERVER_ALIVE_INTERVAL}",
            "-o",
            f"ServerAliveCountMax={_SERVER_ALIVE_COUNT_MAX}",
            "-L",
            f"{socket_path}:{remote_socket}",
            host,
        ]
        process = self._process_factory(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + _START_TIMEOUT
        while time.monotonic() < deadline:
            if socket_path.exists():
                client = self._client_factory(
                    base_url=f"unix://{socket_path}",
                    timeout=_CLIENT_TIMEOUT,
                )
                return _Connection(
                    socket_path=socket_path,
                    client=client,
                    route=SSHRoute(host=host),
                    process=process,
                )
            if process.poll() is not None:
                stderr = process.stderr.read() if process.stderr is not None else b""
                message = stderr.decode("utf-8", "replace").strip()
                raise TransportError(
                    f"SSH Podman tunnel for {host!r} failed: {message or 'ssh exited'}"
                )
            time.sleep(_START_INTERVAL)
        self._stop(process)
        raise TransportError(f"SSH Podman tunnel for {host!r} did not create its socket")

    def _connect_machine(self, host: str, options: HostConfig) -> _Connection:
        machine = options.machine
        if machine is None:
            raise TransportError(f"podman-machine host {host!r} has no machine name")
        try:
            result = self._run_factory(
                ["podman", "machine", "inspect", machine],
                check=True,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=_START_TIMEOUT,
            )
            payload = json.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            raise TransportError(
                f"failed to inspect Podman machine {machine!r} for host {host!r}: {exc}"
            ) from exc
        if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
            raise TransportError(f"Podman machine {machine!r} returned invalid inspect data")
        inspected = payload[0]
        if inspected.get("State") != "running":
            raise TransportError(f"Podman machine {machine!r} is not running")
        if inspected.get("Rootful") is not True:
            raise TransportError(
                f"Podman machine {machine!r} must use rootful mode; "
                f"run: podman machine set --rootful {machine}"
            )
        try:
            socket_path = Path(inspected["ConnectionInfo"]["PodmanSocket"]["Path"])
            ssh_config = inspected["SSHConfig"]
            port = int(ssh_config["Port"])
            identity_path = Path(ssh_config["IdentityPath"])
        except (KeyError, TypeError, ValueError) as exc:
            raise TransportError(f"Podman machine {machine!r} inspect data is incomplete") from exc
        if not socket_path.is_absolute() or not socket_path.exists():
            raise TransportError(
                f"Podman machine {machine!r} API socket is unavailable: {socket_path}"
            )
        if not identity_path.is_absolute() or not identity_path.is_file():
            raise TransportError(
                f"Podman machine {machine!r} SSH identity is unavailable: {identity_path}"
            )
        client = self._client_factory(
            base_url=f"unix://{socket_path}",
            timeout=_CLIENT_TIMEOUT,
        )
        return _Connection(
            socket_path=socket_path,
            client=client,
            route=SSHRoute(
                host=host,
                machine=machine,
                port=port,
                identity_path=identity_path,
            ),
        )

    @staticmethod
    def _stop(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        process.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=2)
        if process.poll() is None:
            process.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=2)
