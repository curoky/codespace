"""Podman clients, SSH tunnels and remote command / atomic file primitives.

One OpenSSH ControlMaster is kept per host: the master process holds the Podman
API socket forward; per-Workspace agent sockets are added with ``ssh -O forward``.
Command execution and the SSH login probe reuse the same control socket, so a
single base option set describes every SSH invocation. The ``run_host`` /
``write_atomic`` / ``ensure_mode`` helpers carry no Codespace layout knowledge.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import stat
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping
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
class HostEndpoint:
    """Neutral Podman connection endpoint for one SSH host."""

    podman_socket: str | None = None  # None falls back to /run/podman/podman.sock

    def resolved_podman_socket(self) -> str:
        return self.podman_socket or _PODMAN_SOCKET


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


def write_atomic(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` atomically with ``0o700`` dir/``0o600`` file modes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ensure_mode(path.parent, 0o700)
    if path.exists() and path.read_text(encoding="utf-8") == content:
        ensure_mode(path, 0o600)
        return
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        temporary_path = Path(temporary_name)
        ensure_mode(temporary_path, 0o600)
        temporary_path.replace(path)
    finally:
        if temporary_name:
            with contextlib.suppress(FileNotFoundError):
                Path(temporary_name).unlink()


def ensure_mode(path: Path, mode: int) -> None:
    if stat.S_IMODE(path.stat().st_mode) != mode:
        path.chmod(mode)


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


ProcessFactory = Callable[..., subprocess.Popen[bytes]]
ClientFactory = Callable[..., PodmanClient]
RunFactory = Callable[..., subprocess.CompletedProcess[bytes]]


class PodmanTransport:
    """Own reusable Podman connections and SSH tunnels for configured hosts."""

    def __init__(
        self,
        hosts: Mapping[str, HostEndpoint],
        *,
        runtime_parent: Path | None = None,
        process_factory: ProcessFactory = subprocess.Popen,
        client_factory: ClientFactory = PodmanClient,
        run_factory: RunFactory = subprocess.run,
    ) -> None:
        self._hosts = dict(hosts)
        # OpenSSH adds a temporary suffix while binding; macOS limits Unix paths to 103 bytes.
        parent = runtime_parent if runtime_parent is not None else _DEFAULT_RUNTIME_PARENT
        self._runtime_dir = Path(tempfile.mkdtemp(prefix="codespace-", dir=parent))
        self._runtime_dir.chmod(0o700)
        self._process_factory = process_factory
        self._client_factory = client_factory
        self._run_factory = run_factory
        self._masters: dict[str, _Master] = {}
        self._locks = {host: Lock() for host in hosts}
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

    def close(self) -> None:
        """Close Podman clients, SSH masters, and the runtime directory."""
        if self._closed:
            return
        self._closed = True
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
        master = self._start_master(host, self._hosts[host])
        self._masters[host] = master
        return master

    def _start_master(self, host: str, options: HostEndpoint) -> _Master:
        digest = hashlib.sha256(host.encode()).hexdigest()[:16]
        control_path = self._runtime_dir / f"control-{digest}.sock"
        socket_path = self._runtime_dir / f"podman-{digest}.sock"
        control_path.unlink(missing_ok=True)
        socket_path.unlink(missing_ok=True)
        command = [
            "ssh",
            "-N",
            *ssh_base_options(control_path),
            "-o",
            "ControlMaster=yes",
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "StreamLocalBindUnlink=yes",
            "-o",
            f"ServerAliveInterval={_SERVER_ALIVE_INTERVAL}",
            "-o",
            f"ServerAliveCountMax={_SERVER_ALIVE_COUNT_MAX}",
            "-L",
            f"{socket_path}:{options.resolved_podman_socket()}",
            host,
        ]
        process = self._process_factory(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        self._await_control_socket(process, control_path)
        client = self._client_factory(
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
        result = self._run_factory(
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
