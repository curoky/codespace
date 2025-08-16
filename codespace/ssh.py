"""Login-key management, SSH probes and generated Codespace projections."""

from __future__ import annotations

import fcntl
import os
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

from codespace.models import CONTAINER_USER, Environment

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


def initialize(hosts: list[str]) -> None:
    """Create the managed SSH layout and remove projections for deleted hosts."""
    with _layout_lock():
        _ensure_main_include()
        _write(CODESPACE_CONFIG_PATH, f"{HOSTS_INCLUDE_LINE}\n")
        HOSTS_DIR.mkdir(parents=True, exist_ok=True)
        HOSTS_DIR.chmod(0o700)
        configured = {f"{host}.conf" for host in hosts}
        for path in HOSTS_DIR.glob("*.conf"):
            if path.name not in configured:
                path.unlink()


def ensure_login_key() -> str:
    """Generate or reuse the single passwordless Codespace login keypair."""
    with _layout_lock():
        CODESPACE_DIR.mkdir(parents=True, exist_ok=True)
        CODESPACE_DIR.chmod(0o700)
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
        LOGIN_KEY_PATH.chmod(0o600)
        if not public_path.exists():
            result = subprocess.run(  # noqa: S603
                ["ssh-keygen", "-y", "-f", str(LOGIN_KEY_PATH)],  # noqa: S607
                check=True,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
            )
            public_path.write_text(result.stdout.rstrip() + "\n", encoding="utf-8")
        public_path.chmod(0o600)
        return public_path.read_text(encoding="utf-8").strip()


def probe(environment: Environment) -> None:
    """Verify actual SSH login through the configured host alias and login key."""
    known_hosts = KNOWN_HOSTS_DIR / environment.id
    known_hosts.parent.mkdir(parents=True, exist_ok=True)
    known_hosts.parent.chmod(0o700)
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
        f"ProxyJump={environment.host}",
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


def write_host(host: str, environments: list[Environment]) -> None:
    """Atomically replace one successfully inventoried host projection."""
    blocks = [
        _render_environment(environment)
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


def _render_environment(environment: Environment) -> str:
    known_hosts = f"~/.ssh/codespace/known_hosts/{environment.id}"
    return "\n".join(
        [
            f"Host {environment.id}",
            "    HostName 127.0.0.1",
            f"    Port {environment.ssh_port}",
            f"    User {CONTAINER_USER}",
            f"    ProxyJump {environment.host}",
            "    IdentityFile ~/.ssh/codespace/id_ed25519",
            "    IdentitiesOnly yes",
            "    HostKeyAlgorithms ssh-ed25519",
            "    StrictHostKeyChecking accept-new",
            f"    UserKnownHostsFile {known_hosts}",
            "    UpdateHostKeys no",
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
        SSH_CONFIG_PATH.chmod(0o600)


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
    path.parent.chmod(0o700)
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
        temporary_path.chmod(0o600)
        temporary_path.replace(path)
    finally:
        if temporary_name:
            with suppress(FileNotFoundError):
                Path(temporary_name).unlink()


@contextmanager
def _layout_lock() -> Iterator[None]:
    with _LOCK:
        CODESPACE_DIR.mkdir(parents=True, exist_ok=True)
        CODESPACE_DIR.chmod(0o700)
        lock_path = CODESPACE_DIR / ".lock"
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            lock_path.chmod(0o600)
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
