"""Provider-neutral remote command execution and atomic local file writes.

These primitives carry no Codespace layout knowledge: :func:`run_host` runs one
command over an SSH route (either a configured SSH host or a Podman Machine),
and :func:`write_atomic`/:func:`ensure_mode` manage local files with strict
permissions. Callers own every path and route the operations act on.
"""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
from contextlib import suppress
from pathlib import Path

from controller.runtime.transport import SSHRoute


def run_host(
    route: SSHRoute,
    remote_command: str,
    *,
    timeout: float,
    action: str,
    machine_known_hosts: Path | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one command over an SSH route and return the completed process.

    For a Podman Machine route the caller must provide ``machine_known_hosts``;
    its parent directory is created with ``0o700`` before use.
    """
    command = ["ssh", "-o", "BatchMode=yes"]
    if route.is_machine:
        if route.port is None or route.identity_path is None:
            raise RuntimeError(f"Podman Machine SSH route for {route.host!r} is incomplete")
        if machine_known_hosts is None:
            raise RuntimeError(
                f"Podman Machine SSH route for {route.host!r} requires a known_hosts path"
            )
        machine_known_hosts.parent.mkdir(parents=True, exist_ok=True)
        ensure_mode(machine_known_hosts.parent, 0o700)
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
            stdin=subprocess.DEVNULL if input_text is None else None,
            input=input_text,
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
            with suppress(FileNotFoundError):
                Path(temporary_name).unlink()


def ensure_mode(path: Path, mode: int) -> None:
    if stat.S_IMODE(path.stat().st_mode) != mode:
        path.chmod(mode)
