"""Workspace SSH routes using the macOS client contract."""

from __future__ import annotations

import os
import shlex
import tempfile
from pathlib import Path

from codespace.runtime.transport import SSHRoute, ssh_base_options
from codespace.workspaces import Workspace

SSH_CONFIG_PATH = Path("/Users/x/.ssh/codespace/config")
SSH_ROUTES_DIR = Path("/Users/x/.ssh/codespace/workspaces")


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
