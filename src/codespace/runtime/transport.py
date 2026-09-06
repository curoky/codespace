"""Podman clients, SSH tunnels, and remote command primitives.

One OpenSSH ControlMaster is kept per host: the master process holds the Podman
API socket forward; per-Workspace agent sockets are added with ``ssh -O forward``.
Host commands and Workspace tunnel proxies reuse the same control socket.
"""

from __future__ import annotations

import contextlib
import hashlib
import shutil
import socket
import subprocess
import tempfile
import time
from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock

from podman import PodmanClient

_PODMAN_SOCKET = "/run/podman/podman.sock"
_DEFAULT_RUNTIME_PARENT = Path("/tmp")  # noqa: S108 - short parent; mkdtemp creates mode 0700

_START_TIMEOUT = 10.0
_START_INTERVAL = 0.05
# Cap every Podman call so a half-dead tunnel fails fast instead of hanging.
# Image pulls stream, so this bounds inter-chunk gaps, not the whole download.
_CLIENT_TIMEOUT = 60.0
# Let SSH drop a silently-broken master; the next client() call rebuilds it.
_SERVER_ALIVE_INTERVAL = 15
_SERVER_ALIVE_COUNT_MAX = 3


class TransportError(RuntimeError):
    """Raised when a configured host cannot expose Podman or an SSH route."""


@dataclass(frozen=True, slots=True)
class SSHRoute:
    """Information needed to execute commands and proxy SSH through one host."""

    host: str
    control_path: Path | None = None


def ssh_base_options(control_path: Path | None) -> list[str]:
    """Return the shared SSH ``-o`` options for every control-plane SSH call."""
    options = ["-o", "BatchMode=yes"]
    if control_path is not None:
        options += ["-o", f"ControlPath={control_path}"]
    return options


def run_host(
    route: SSHRoute,
    remote_command: str,
    *,
    timeout: float,
    action: str,
) -> subprocess.CompletedProcess[str]:
    """Run one command over an SSH route and return the completed process."""
    command = ["ssh", *ssh_base_options(route.control_path), route.host, remote_command]
    try:
        return subprocess.run(  # noqa: S603
            command,
            check=True,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        stderr = (
            exc.stderr.strip()
            if isinstance(exc, subprocess.CalledProcessError) and exc.stderr
            else ""
        )
        raise RuntimeError(f"failed to {action} on host {route.host!r}: {stderr or exc}") from exc


@dataclass(slots=True)
class _Master:
    """A live SSH ControlMaster holding the host's Podman socket forward."""

    control_path: Path
    podman_socket_path: Path
    client: PodmanClient
    route: SSHRoute
    process: subprocess.Popen[bytes]
    forwards: dict[str, Path] = field(default_factory=dict)

    def is_running(self) -> bool:
        return self.control_path.exists() and self.process.poll() is None


@dataclass(slots=True)
class _TCPForward:
    control_path: Path
    process: subprocess.Popen[bytes]
    local_port: int
    options: tuple[str, ...]
    connection_id: str


class PodmanTransport:
    """Own reusable Podman connections and SSH tunnels for configured hosts."""

    def __init__(
        self,
        hosts: Collection[str],
        *,
        runtime_parent: Path | None = None,
    ) -> None:
        self._hosts = frozenset(hosts)
        # OpenSSH adds a temporary suffix while binding; macOS limits Unix paths to 103 bytes.
        parent = runtime_parent if runtime_parent is not None else _DEFAULT_RUNTIME_PARENT
        self._runtime_dir = Path(tempfile.mkdtemp(prefix="codespace-", dir=parent))
        self._runtime_dir.chmod(0o700)
        self._masters: dict[str, _Master] = {}
        self._tcp_forwards: dict[tuple[str, str, str, int], _TCPForward] = {}
        self._locks = {host: Lock() for host in hosts}
        self._master_start_lock = Lock()
        self._closed = False

    @property
    def runtime_dir(self) -> Path:
        return self._runtime_dir

    def client(self, host: str) -> PodmanClient:
        """Return a Podman client connected to one live configured host."""
        return self._master(host).client

    def ssh_route(self, host: str) -> SSHRoute:
        """Return the SSH route paired with one live Podman connection."""
        return self._master(host).route

    def forward_socket(self, host: str, remote_socket: str) -> Path:
        """Return a local Unix socket forwarded to one absolute host socket."""
        if not remote_socket.startswith("/"):
            raise TransportError(f"remote Unix socket must be absolute: {remote_socket!r}")
        with self._locks[self._known(host)]:
            master = self._live_master(host)
            existing = master.forwards.get(remote_socket)
            if existing is not None:
                return existing
            digest = hashlib.sha256(f"{host}\0{remote_socket}".encode()).hexdigest()[:16]
            socket_path = self._runtime_dir / f"agent-{digest}.sock"
            socket_path.unlink(missing_ok=True)
            self._control_forward(master, "forward", socket_path, remote_socket)
            master.forwards[remote_socket] = socket_path
            return socket_path

    def forward_tcp(
        self,
        host: str,
        destination: str,
        *,
        port: int,
        remote_host: str = "127.0.0.1",
        local_port: int | None = None,
        options: list[str],
        connection_id: str,
    ) -> int:
        """Expose one remote TCP endpoint over a managed SSH connection."""
        with self._locks[self._known(host)]:
            key = (host, destination, remote_host, port)
            existing = self._tcp_forwards.get(key)
            if existing is not None:
                if (
                    existing.process.poll() is None
                    and existing.control_path.exists()
                    and (local_port is None or existing.local_port == local_port)
                    and existing.options == tuple(options)
                    and existing.connection_id == connection_id
                ):
                    return existing.local_port
                self._stop(existing.process)
                existing.control_path.unlink(missing_ok=True)
                del self._tcp_forwards[key]

            digest = hashlib.sha256(
                f"{host}\0{destination}\0{remote_host}\0{port}".encode()
            ).hexdigest()[:16]
            control_path = self._runtime_dir / f"tcp-{digest}.sock"
            control_path.unlink(missing_ok=True)
            selected_local_port = local_port
            if selected_local_port is None:
                # OpenSSH cannot allocate a local TCP port with -L port 0.
                with socket.socket() as listener:
                    listener.bind(("127.0.0.1", 0))
                    selected_local_port = int(listener.getsockname()[1])
            remote_endpoint = f"[{remote_host}]" if ":" in remote_host else remote_host
            with self._master_start_lock:
                if local_port is not None:
                    for competing_key, competing in list(self._tcp_forwards.items()):
                        if competing.local_port != selected_local_port:
                            continue
                        self._stop(competing.process)
                        competing.control_path.unlink(missing_ok=True)
                        del self._tcp_forwards[competing_key]
                process = self._start_tunnel(
                    control_path,
                    destination,
                    f"127.0.0.1:{selected_local_port}:{remote_endpoint}:{port}",
                    ["-o", "GatewayPorts=no", *options],
                )
                self._tcp_forwards[key] = _TCPForward(
                    control_path, process, selected_local_port, tuple(options), connection_id
                )
            return selected_local_port

    def close_tcp(self, host: str, destination: str) -> None:
        """Release all local listeners and SSH connections for a destination."""
        with self._locks[self._known(host)]:
            for key in [key for key in self._tcp_forwards if key[:2] == (host, destination)]:
                forward = self._tcp_forwards.pop(key)
                self._stop(forward.process)
                forward.control_path.unlink(missing_ok=True)

    def close(self) -> None:
        """Close Podman clients, SSH masters, and the runtime directory."""
        if self._closed:
            return
        self._closed = True
        for host, lock in self._locks.items():
            with lock:
                for key in [key for key in self._tcp_forwards if key[0] == host]:
                    self._stop(self._tcp_forwards.pop(key).process)
        masters = list(self._masters.values())
        self._masters.clear()
        for master in masters:
            master.client.close()  # type: ignore[no-untyped-call]
            self._stop(master.process)
        shutil.rmtree(self._runtime_dir, ignore_errors=True)

    def _known(self, host: str) -> str:
        if self._closed:
            raise TransportError("Podman transport is closed")
        if host not in self._hosts:
            raise TransportError(f"unknown host: {host}")
        return host

    def _master(self, host: str) -> _Master:
        with self._locks[self._known(host)]:
            return self._live_master(host)

    def _live_master(self, host: str) -> _Master:
        master = self._masters.get(host)
        if master is not None and master.is_running():
            return master
        if master is not None:
            master.client.close()  # type: ignore[no-untyped-call]
            self._stop(master.process)
            master.podman_socket_path.unlink(missing_ok=True)
        # Hosts may share a GSSAPI ProxyJump whose credential cache cannot authenticate
        # concurrent SSH processes reliably. Only serialize the initial handshakes.
        with self._master_start_lock:
            master = self._start_master(host)
        self._masters[host] = master
        return master

    def _start_master(self, host: str) -> _Master:
        digest = hashlib.sha256(host.encode()).hexdigest()[:16]
        control_path = self._runtime_dir / f"control-{digest}.sock"
        socket_path = self._runtime_dir / f"podman-{digest}.sock"
        control_path.unlink(missing_ok=True)
        socket_path.unlink(missing_ok=True)
        process = self._start_tunnel(
            control_path,
            host,
            f"{socket_path}:{_PODMAN_SOCKET}",
            ["-o", "StreamLocalBindUnlink=yes"],
        )
        client = PodmanClient(
            base_url=f"unix://{socket_path}",
            timeout=_CLIENT_TIMEOUT,
        )
        return _Master(
            control_path=control_path,
            podman_socket_path=socket_path,
            client=client,
            route=SSHRoute(host=host, control_path=control_path),
            process=process,
        )

    def _start_tunnel(
        self, control_path: Path, destination: str, forward: str, options: list[str]
    ) -> subprocess.Popen[bytes]:
        command = [
            "ssh",
            "-N",
            *ssh_base_options(control_path),
            "-o",
            "ControlMaster=yes",
            "-o",
            "ControlPersist=no",
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            f"ServerAliveInterval={_SERVER_ALIVE_INTERVAL}",
            "-o",
            f"ServerAliveCountMax={_SERVER_ALIVE_COUNT_MAX}",
            *options,
            "-L",
            forward,
            destination,
        ]
        process = subprocess.Popen(  # noqa: S603
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            self._await_control_socket(process, control_path)
        except BaseException:
            self._stop(process)
            control_path.unlink(missing_ok=True)
            raise
        return process

    def _await_control_socket(
        self,
        process: subprocess.Popen[bytes],
        control_path: Path,
    ) -> None:
        deadline = time.monotonic() + _START_TIMEOUT
        while time.monotonic() < deadline:
            if process.poll() is not None:
                stderr = process.stderr.read() if process.stderr is not None else b""
                message = stderr.decode("utf-8", "replace").strip()
                raise TransportError(f"SSH master exited: {message or 'ssh exited'}")
            if control_path.exists():
                return
            time.sleep(_START_INTERVAL)
        self._stop(process)
        raise TransportError(f"SSH master did not create control socket {control_path}")

    def _control_forward(
        self,
        master: _Master,
        action: str,
        socket_path: Path,
        remote_socket: str,
    ) -> None:
        command = [
            "ssh",
            "-O",
            action,
            *ssh_base_options(master.control_path),
            "-o",
            "StreamLocalBindUnlink=yes",
            "-L",
            f"{socket_path}:{remote_socket}",
            master.route.host,
        ]
        result = subprocess.run(  # noqa: S603
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            stderr = (result.stderr or b"").decode("utf-8", "replace").strip()
            raise TransportError(
                f"SSH -O {action} for {master.route.host!r} failed: {stderr or 'ssh exited'}"
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
