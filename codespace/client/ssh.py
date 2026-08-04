"""Login-key management, SSH probes and generated Codespace projections."""

from __future__ import annotations

import fcntl
import os
import shlex
import stat
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from functools import cache
from pathlib import Path

from codespace.client.models import (
    CONTAINER_USER,
    WORKSPACE_DIR_NAME,
    Environment,
)
from codespace.client.transport import SSHRoute

SSH_CONFIG_PATH = Path.home() / ".ssh" / "config"
CODESPACE_DIR = Path.home() / ".ssh" / "codespace"
CODESPACE_CONFIG_PATH = CODESPACE_DIR / "config"
HOSTS_DIR = CODESPACE_DIR / "hosts"
KNOWN_HOSTS_DIR = CODESPACE_DIR / "known_hosts"
LOGIN_KEY_PATH = CODESPACE_DIR / "id_ed25519"
INCLUDE_LINE = "Include ~/.ssh/codespace/config"
HOSTS_INCLUDE_LINE = "Include ~/.ssh/codespace/hosts/*.conf"
_LOCK = threading.RLock()
_PROBE_TIMEOUT = 30.0
_PROBE_INTERVAL = 0.5
_WORKSPACE_ROOT_TIMEOUT = 15.0
_WORKSPACE_PREPARE_TIMEOUT = 15.0


@cache
def remote_workspace_root(route: SSHRoute) -> str:
    """Resolve and ensure one host's workspace root under the login user's home.

    A Podman bind-mount source cannot contain ``~``, so the absolute path is
    resolved per route with one cached SSH round-trip that also creates the
    directory. Ensuring it here means the bind-mount source always exists.
    """
    # WORKSPACE_DIR_NAME is a fixed internal constant, so this remote command is
    # not exposed to injection; "$HOME" expands in the remote login shell.
    remote_command = (
        f'mkdir -p -- "$HOME/{WORKSPACE_DIR_NAME}" && printf %s "$HOME/{WORKSPACE_DIR_NAME}"'
    )
    result = _run_host(
        route,
        remote_command,
        timeout=_WORKSPACE_ROOT_TIMEOUT,
        action="resolve workspace root",
    )
    root = result.stdout.strip()
    if not root.startswith("/"):
        raise RuntimeError(f"host {route.host!r} returned a non-absolute workspace root: {root!r}")
    return root


def prepare_workspace(route: SSHRoute, target: str) -> None:
    """Create one environment's workspace directory through its host route.

    The directory is created as the plain SSH login user without any privilege
    escalation, so hosts do not need passwordless ``sudo``. Ownership is left as
    the login user here; the container fixes it to the container uid/gid from the
    inside via ``runtime.own_workspace`` (rootful Podman exposes host ownership
    directly, so an in-container ``chown`` as root also updates the host path).
    """
    if not target.startswith("/"):
        raise RuntimeError(f"refusing to prepare non-absolute workspace path: {target!r}")
    remote_command = f"mkdir -p -- {shlex.quote(target)}"
    _run_host(
        route,
        remote_command,
        timeout=_WORKSPACE_PREPARE_TIMEOUT,
        action=f"prepare workspace {target!r}",
    )


def _run_host(
    route: SSHRoute,
    remote_command: str,
    *,
    timeout: float,
    action: str,
) -> subprocess.CompletedProcess[str]:
    command = ["ssh", "-o", "BatchMode=yes"]
    if route.is_machine:
        if route.port is None or route.identity_path is None:
            raise RuntimeError(f"Podman Machine SSH route for {route.host!r} is incomplete")
        machine_known_hosts = _machine_known_hosts(route)
        machine_known_hosts.parent.mkdir(parents=True, exist_ok=True)
        _ensure_mode(machine_known_hosts.parent, 0o700)
        command.extend(
            [
                "-o",
                "IdentitiesOnly=yes",
                "-o",
                "StrictHostKeyChecking=accept-new",
                "-o",
                f"UserKnownHostsFile={machine_known_hosts}",
                "-i",
                str(route.identity_path),
                "-p",
                str(route.port),
                "root@127.0.0.1",
            ]
        )
    else:
        command.append(route.host)
    command.append(remote_command)
    try:
        result = subprocess.run(  # noqa: S603
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
    return result


def initialize(hosts: list[str]) -> None:
    """Create the managed SSH layout and remove projections for deleted hosts."""
    with _layout_lock():
        _ensure_main_include()
        _write(CODESPACE_CONFIG_PATH, f"{HOSTS_INCLUDE_LINE}\n")
        HOSTS_DIR.mkdir(parents=True, exist_ok=True)
        _ensure_mode(HOSTS_DIR, 0o700)
        configured = {f"{host}.conf" for host in hosts}
        for path in HOSTS_DIR.glob("*.conf"):
            if path.name not in configured:
                path.unlink()


def ensure_login_key() -> str:
    """Generate or reuse the single passwordless Codespace login keypair."""
    with _layout_lock():
        CODESPACE_DIR.mkdir(parents=True, exist_ok=True)
        _ensure_mode(CODESPACE_DIR, 0o700)
        public_path = LOGIN_KEY_PATH.with_suffix(".pub")
        if not LOGIN_KEY_PATH.exists() or LOGIN_KEY_PATH.stat().st_size == 0:
            LOGIN_KEY_PATH.unlink(missing_ok=True)
            public_path.unlink(missing_ok=True)
            subprocess.run(  # noqa: S603
                [  # noqa: S607
                    "ssh-keygen",
                    "-t",
                    "ed25519",
                    "-f",
                    str(LOGIN_KEY_PATH),
                    "-N",
                    "",
                ],
                check=True,
                capture_output=True,
                stdin=subprocess.DEVNULL,
            )
        _ensure_mode(LOGIN_KEY_PATH, 0o600)
        if not public_path.exists():
            result = subprocess.run(  # noqa: S603
                ["ssh-keygen", "-y", "-f", str(LOGIN_KEY_PATH)],  # noqa: S607
                check=True,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
            )
            public_path.write_text(result.stdout.rstrip() + "\n", encoding="utf-8")
        _ensure_mode(public_path, 0o600)
        return public_path.read_text(encoding="utf-8").strip()


def probe(environment: Environment, route: SSHRoute) -> None:
    """Verify actual SSH login through the configured host alias and login key."""
    known_hosts = KNOWN_HOSTS_DIR / environment.id
    known_hosts.parent.mkdir(parents=True, exist_ok=True)
    _ensure_mode(known_hosts.parent, 0o700)
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "HostName=127.0.0.1",
        "-o",
        f"Port={environment.ssh_port}",
        "-o",
        f"User={CONTAINER_USER}",
        "-o",
        _proxy_option(route),
        "-o",
        f"IdentityFile={LOGIN_KEY_PATH}",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "HostKeyAlgorithms=ssh-ed25519",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        "-o",
        "UpdateHostKeys=no",
        environment.id,
        "true",
    ]
    deadline = time.monotonic() + _PROBE_TIMEOUT
    while True:
        try:
            subprocess.run(  # noqa: S603
                command,
                check=True,
                capture_output=True,
                stdin=subprocess.DEVNULL,
            )
            return
        except subprocess.CalledProcessError as exc:
            if time.monotonic() >= deadline:
                stderr = exc.stderr.decode("utf-8", "replace") if exc.stderr else ""
                raise RuntimeError(
                    f"SSH login probe for {environment.id!r} failed: {stderr.strip() or exc}"
                ) from exc
            time.sleep(_PROBE_INTERVAL)


def write_host(host: str, environments: list[Environment], route: SSHRoute) -> None:
    """Atomically replace one successfully inventoried host projection."""
    if route.host != host:
        raise ValueError(f"SSH route {route.host!r} does not match host {host!r}")
    blocks = [
        _render_environment(environment, route)
        for environment in sorted(
            environments,
            key=lambda item: (item.project, item.instance),
        )
    ]
    content = "\n\n".join(blocks)
    if content:
        content += "\n"
    with _layout_lock():
        _write(HOSTS_DIR / f"{host}.conf", content)


def _render_environment(environment: Environment, route: SSHRoute) -> str:
    known_hosts = f"~/.ssh/codespace/known_hosts/{environment.id}"
    proxy_directive = _proxy_option(route).replace("=", " ", 1)
    return "\n".join(
        [
            f"Host {environment.id}",
            "    HostName 127.0.0.1",
            f"    Port {environment.ssh_port}",
            f"    User {CONTAINER_USER}",
            f"    {proxy_directive}",
            "    IdentityFile ~/.ssh/codespace/id_ed25519",
            "    IdentitiesOnly yes",
            "    HostKeyAlgorithms ssh-ed25519",
            "    StrictHostKeyChecking accept-new",
            f"    UserKnownHostsFile {known_hosts}",
            "    UpdateHostKeys no",
        ]
    )


def _proxy_option(route: SSHRoute) -> str:
    if not route.is_machine:
        return f"ProxyJump={route.host}"
    if route.port is None or route.identity_path is None:
        raise RuntimeError(f"Podman Machine SSH route for {route.host!r} is incomplete")
    machine_known_hosts = _machine_known_hosts(route)
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"UserKnownHostsFile={machine_known_hosts}",
        "-i",
        str(route.identity_path),
        "-p",
        str(route.port),
        "-W",
        "%h:%p",
        "root@127.0.0.1",
    ]
    return f"ProxyCommand={shlex.join(command)}"


def _machine_known_hosts(route: SSHRoute) -> Path:
    return KNOWN_HOSTS_DIR / f"machine-{route.host}"


def _ensure_main_include() -> None:
    content = SSH_CONFIG_PATH.read_text(encoding="utf-8") if SSH_CONFIG_PATH.exists() else ""
    lines = [line for line in content.splitlines() if not _is_codespace_include(line)]
    body = "\n".join(lines).strip("\n")
    updated = f"{INCLUDE_LINE}\n\n{body}\n" if body else f"{INCLUDE_LINE}\n"
    if updated != content:
        _write(SSH_CONFIG_PATH, updated)
    elif SSH_CONFIG_PATH.exists():
        _ensure_mode(SSH_CONFIG_PATH, 0o600)


def _is_codespace_include(line: str) -> bool:
    content = line.split("#", 1)[0].strip()
    parts = content.split()
    if not parts or parts[0].lower() != "include":
        return False
    return any(
        target.strip("'\"") in {"~/.ssh/codespace/config", str(CODESPACE_CONFIG_PATH)}
        for target in parts[1:]
    )


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_mode(path.parent, 0o700)
    if path.exists() and path.read_text(encoding="utf-8") == content:
        _ensure_mode(path, 0o600)
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
        _ensure_mode(temporary_path, 0o600)
        temporary_path.replace(path)
    finally:
        if temporary_name:
            with suppress(FileNotFoundError):
                Path(temporary_name).unlink()


def _ensure_mode(path: Path, mode: int) -> None:
    if stat.S_IMODE(path.stat().st_mode) != mode:
        path.chmod(mode)


@contextmanager
def _layout_lock() -> Iterator[None]:
    with _LOCK:
        CODESPACE_DIR.mkdir(parents=True, exist_ok=True)
        _ensure_mode(CODESPACE_DIR, 0o700)
        lock_path = CODESPACE_DIR / ".lock"
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            _ensure_mode(lock_path, 0o600)
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
