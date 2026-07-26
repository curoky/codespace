"""System-SSH transport for remote rootful Podman sockets."""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from podman import PodmanClient

_START_TIMEOUT = 10.0
_START_INTERVAL = 0.05


class TransportError(RuntimeError):
    """Raised when an SSH tunnel cannot expose the remote Podman socket."""


@dataclass(slots=True)
class _Tunnel:
    socket_path: Path
    process: subprocess.Popen[bytes]
    client: PodmanClient

    def is_running(self) -> bool:
        return self.process.poll() is None and self.socket_path.exists()


ProcessFactory = Callable[..., subprocess.Popen[bytes]]
ClientFactory = Callable[..., PodmanClient]


class PodmanTransport:
    """Reuse one system SSH Unix-socket forward per configured host."""

    def __init__(
        self,
        host_sockets: Mapping[str, str],
        *,
        runtime_parent: Path | None = None,
        process_factory: ProcessFactory = subprocess.Popen,
        client_factory: ClientFactory = PodmanClient,
    ) -> None:
        self._host_sockets = dict(host_sockets)
        self._hosts = set(host_sockets)
        self._runtime_dir = Path(tempfile.mkdtemp(prefix="codespace-", dir=runtime_parent))
        self._runtime_dir.chmod(0o700)
        self._process_factory = process_factory
        self._client_factory = client_factory
        self._tunnels: dict[str, _Tunnel] = {}
        self._locks = {host: Lock() for host in host_sockets}
        self._closed = False

    @property
    def runtime_dir(self) -> Path:
        return self._runtime_dir

    def client(self, host: str) -> PodmanClient:
        """Return a Podman client connected through a live host tunnel."""
        if self._closed:
            raise TransportError("Podman transport is closed")
        if host not in self._hosts:
            raise TransportError(f"unknown host: {host}")
        return self._tunnel(host).client

    def close(self) -> None:
        """Stop all SSH children and remove the process runtime directory."""
        if self._closed:
            return
        self._closed = True
        tunnels = list(self._tunnels.values())
        self._tunnels.clear()
        for tunnel in tunnels:
            tunnel.client.close()
            self._stop(tunnel.process)
        shutil.rmtree(self._runtime_dir, ignore_errors=True)

    def _tunnel(self, host: str) -> _Tunnel:
        lock = self._locks[host]
        with lock:
            tunnel = self._tunnels.get(host)
            if tunnel is not None and tunnel.is_running():
                return tunnel
            if tunnel is not None:
                tunnel.client.close()
                self._stop(tunnel.process)
                tunnel.socket_path.unlink(missing_ok=True)
            tunnel = self._start(host)
            self._tunnels[host] = tunnel
            return tunnel

    def _start(self, host: str) -> _Tunnel:
        socket_path = self._runtime_dir / f"{host}.sock"
        socket_path.unlink(missing_ok=True)
        remote_socket = self._host_sockets[host]
        command = [
            "ssh",
            "-N",
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "StreamLocalBindUnlink=yes",
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
                client = self._client_factory(base_url=f"unix://{socket_path}")
                return _Tunnel(
                    socket_path=socket_path,
                    process=process,
                    client=client,
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
