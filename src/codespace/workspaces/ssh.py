"""Workspace SSH connection options and login probes."""

from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
import time
from pathlib import Path

from tenacity import Retrying, retry_if_exception_type, stop_after_delay, wait_fixed

from codespace.runtime.transport import SSHRoute, ssh_base_options
from codespace.workspaces.models import Workspace

SSH_CONFIG_PATH = Path("/Users/x/.ssh/codespace/config")
SSH_ROUTES_DIR = Path("/Users/x/.ssh/codespace/workspaces")

_PROBE_TIMEOUT = 30.0
_PROBE_INTERVAL = 0.5


def connection_options(workspace: Workspace, route: SSHRoute) -> list[str]:
    """Apply the fixed client contract through the Host's authenticated connection."""
    proxy = shlex.join(["ssh", *ssh_base_options(route.control_path), "-W", "%h:%p", route.host])
    return [
        "-F",
        str(SSH_CONFIG_PATH),
        "-o",
        f"Port={workspace.ssh_host_port}",
        "-o",
        f"ProxyCommand={proxy}",
    ]


def write_route(workspace: Workspace) -> None:
    """Persist one external SSH route without sharing mutable files."""
    proxy = shlex.join(["ssh", *ssh_base_options(None), "-W", "%h:%p", workspace.host])
    content = "\n".join(
        [
            f"Host {workspace.ssh_alias}",
            "  HostName 127.0.0.1",
            f"  Port {workspace.ssh_host_port}",
            f"  ProxyCommand {proxy}",
            "",
        ]
    )
    SSH_ROUTES_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    SSH_ROUTES_DIR.chmod(0o700)
    path = SSH_ROUTES_DIR / workspace.ssh_alias
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{workspace.ssh_alias}.",
        dir=SSH_ROUTES_DIR,
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as route:
            os.fchmod(route.fileno(), 0o600)
            route.write(content)
            route.flush()
            os.fsync(route.fileno())
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def remove_route(workspace: Workspace) -> None:
    """Remove the external SSH route for one deleted Workspace."""
    (SSH_ROUTES_DIR / workspace.ssh_alias).unlink(missing_ok=True)


def probe(workspace: Workspace, route: SSHRoute) -> None:
    """Verify actual SSH login through the Workspace alias."""
    command = [
        "ssh",
        *ssh_base_options(None),
        *connection_options(workspace, route),
        workspace.ssh_alias,
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
