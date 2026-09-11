"""Workspace SSH connection options and login probes."""

from __future__ import annotations

import shlex
import subprocess
import time
from pathlib import Path

from tenacity import Retrying, retry_if_exception_type, stop_after_delay, wait_fixed

from codespace.runtime.transport import SSHRoute, ssh_base_options
from codespace.workspaces.models import Workspace

SSH_CONFIG_PATH = Path("/Users/x/.ssh/codespace/config")

_PROBE_TIMEOUT = 30.0
_PROBE_INTERVAL = 0.5


def connection_options(workspace: Workspace, route: SSHRoute) -> list[str]:
    """Apply the fixed client contract through the Host's authenticated connection."""
    proxy = shlex.join(["ssh", *ssh_base_options(route.control_path), "-W", "%h:%p", route.host])
    return [
        "-F",
        str(SSH_CONFIG_PATH),
        "-o",
        f"Port={workspace.ssh_port}",
        "-o",
        f"ProxyCommand={proxy}",
    ]


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
