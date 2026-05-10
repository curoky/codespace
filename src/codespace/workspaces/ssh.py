"""Local SSH assets, login probes, and Workspace projections."""

from __future__ import annotations

import fcntl
import subprocess
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from tenacity import Retrying, retry_if_exception_type, stop_after_delay, wait_fixed

from codespace.runtime import transport
from codespace.runtime.transport import SSHRoute, ssh_base_options
from codespace.workspaces.models import CONTAINER_USER, Workspace

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


def initialize(hosts: list[str]) -> None:
    """Create the managed SSH layout and remove projections for deleted Hosts."""
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


def probe(workspace: Workspace, route: SSHRoute) -> None:
    """Verify actual SSH login through the Workspace alias."""
    command = [
        "ssh",
        *ssh_base_options(None),
        "-o",
        "ConnectTimeout=10",
        "-o",
        "HostName=127.0.0.1",
        "-o",
        f"Port={workspace.ssh_port}",
        "-o",
        f"User={CONTAINER_USER}",
        "-o",
        f"ProxyJump={route.host}",
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
        workspace.id,
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
            f"SSH login probe for {workspace.id!r} failed: {stderr.strip() or exc}"
        ) from exc


def write_host(host: str, workspaces: list[Workspace], route: SSHRoute) -> None:
    """Atomically replace one successfully inventoried Host projection."""
    if route.host != host:
        raise ValueError(f"SSH route {route.host!r} does not match host {host!r}")
    blocks = [
        _render_workspace(workspace, route)
        for workspace in sorted(workspaces, key=lambda item: (item.project, item.workspace))
    ]
    content = "\n\n".join(blocks)
    if content:
        content += "\n"
    with _layout_lock():
        _write(HOSTS_DIR / f"{host}.conf", content)


def _render_workspace(workspace: Workspace, route: SSHRoute) -> str:
    return "\n".join(
        [
            f"Host {workspace.id}",
            f"    Port {workspace.ssh_port}",
            f"    ProxyJump {route.host}",
        ]
    )


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
    transport.write_atomic(path, content)


def _ensure_mode(path: Path, mode: int) -> None:
    transport.ensure_mode(path, mode)


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
