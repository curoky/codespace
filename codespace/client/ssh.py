"""Managed SSH assets, login probes and dynamic Codespace projections."""

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

from tenacity import Retrying, retry_if_exception_type, stop_after_delay, wait_fixed

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
INCLUDE_LINE = "Include ~/.ssh/codespace/config"
HOST_KEY_ALIAS = "codespace"
KNOWN_HOSTS_PATH = KNOWN_HOSTS_DIR / HOST_KEY_ALIAS
LOGIN_KEY_PATH = CODESPACE_DIR / "login_key"
SSH_ASSETS_DIR = Path(__file__).resolve().parent / "assets" / "ssh"
SSH_CONFIG_ASSET = SSH_ASSETS_DIR / "config"
KNOWN_HOSTS_ASSET = SSH_ASSETS_DIR / "known_hosts"
LOGIN_KEY_ASSET = SSH_ASSETS_DIR / "login_key"
_LOCK = threading.RLock()
_PROBE_TIMEOUT = 30.0
_PROBE_INTERVAL = 0.5
_WORKSPACE_ROOT_TIMEOUT = 15.0
_WORKSPACE_PREPARE_TIMEOUT = 15.0
_WORKSPACE_LIST_TIMEOUT = 30.0
_HOST_ENVIRONMENT_TIMEOUT = 15.0


@cache
def remote_workspace_root(route: SSHRoute) -> str:
    """Resolve and create the absolute workspace root for one SSH route."""
    # The fixed directory name is safe for expansion by the remote shell.
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
    """Create an environment workspace as the host login user."""
    if not target.startswith("/"):
        raise RuntimeError(f"refusing to prepare non-absolute workspace path: {target!r}")
    remote_command = f"mkdir -p -- {shlex.quote(target)}"
    _run_host(
        route,
        remote_command,
        timeout=_WORKSPACE_PREPARE_TIMEOUT,
        action=f"prepare workspace {target!r}",
    )


def list_workspaces(route: SSHRoute, workspace_root: str) -> list[str]:
    """List ``<project>/<instance>`` directories below a workspace root."""
    if not workspace_root.startswith("/"):
        raise RuntimeError(f"refusing to list non-absolute workspace root: {workspace_root!r}")
    result = _run_host(
        route,
        (f"find {shlex.quote(workspace_root)} -mindepth 2 -maxdepth 2 -type d -print0"),
        timeout=_WORKSPACE_LIST_TIMEOUT,
        action=f"list workspaces below {workspace_root!r}",
    )
    prefix = workspace_root.rstrip("/") + "/"
    workspaces = [path for path in result.stdout.split("\0") if path]
    if any(not path.startswith(prefix) for path in workspaces):
        raise RuntimeError(f"host {route.host!r} returned a workspace outside {workspace_root!r}")
    return sorted(workspaces)


def read_host_environment(route: SSHRoute, names: list[str]) -> dict[str, str]:
    """Read selected exported variables from a remote SSH login environment."""
    if not names:
        return {}
    if route.is_machine:
        raise RuntimeError("host environment inheritance is not supported for Podman Machine")
    result = _run_host(
        route,
        "env -0",
        timeout=_HOST_ENVIRONMENT_TIMEOUT,
        action="read exported environment",
    )
    requested = set(names)
    environment: dict[str, str] = {}
    for entry in result.stdout.split("\0"):
        name, separator, value = entry.partition("=")
        if not separator or name not in requested:
            continue
        if name in environment:
            raise RuntimeError(
                f"host {route.host!r} exported environment variable {name!r} more than once"
            )
        environment[name] = value
    missing = sorted(requested - environment.keys())
    if missing:
        raise RuntimeError(
            f"host {route.host!r} does not export configured environment variables: {missing}"
        )
    return {name: environment[name] for name in names}


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
    assets = (
        (SSH_CONFIG_ASSET, CODESPACE_CONFIG_PATH),
        (KNOWN_HOSTS_ASSET, KNOWN_HOSTS_PATH),
        (LOGIN_KEY_ASSET, LOGIN_KEY_PATH),
    )
    contents = [(destination, _read_asset(source)) for source, destination in assets]
    with _layout_lock():
        _ensure_main_include()
        for destination, content in contents:
            _write(destination, content)
        HOSTS_DIR.mkdir(parents=True, exist_ok=True)
        _ensure_mode(HOSTS_DIR, 0o700)
        configured = {f"{host}.conf" for host in hosts}
        for path in HOSTS_DIR.glob("*.conf"):
            if path.name not in configured:
                path.unlink()


def probe(environment: Environment, route: SSHRoute) -> None:
    """Verify actual SSH login through the configured host alias and login key."""
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
        f"HostKeyAlias={HOST_KEY_ALIAS}",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={KNOWN_HOSTS_PATH}",
        "-o",
        "UpdateHostKeys=no",
        environment.id,
        "true",
    ]
    retryer = Retrying(
        retry=retry_if_exception_type(subprocess.CalledProcessError),
        stop=stop_after_delay(_PROBE_TIMEOUT),
        wait=wait_fixed(_PROBE_INTERVAL),
        sleep=time.sleep,
        reraise=True,
    )
    try:
        retryer(
            subprocess.run,
            command,
            check=True,
            capture_output=True,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", "replace") if exc.stderr else ""
        raise RuntimeError(
            f"SSH login probe for {environment.id!r} failed: {stderr.strip() or exc}"
        ) from exc


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
    proxy_directive = _proxy_option(route).replace("=", " ", 1)
    return "\n".join(
        [
            f"Host {environment.id}",
            f"    Port {environment.ssh_port}",
            f"    {proxy_directive}",
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


def _read_asset(path: Path) -> str:
    if not path.is_file():
        raise RuntimeError(f"SSH asset is missing: {path}")
    return path.read_text(encoding="utf-8")


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
