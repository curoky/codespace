"""Remote Host data layout and bounded command primitives."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from functools import cache

from codespace.runtime import transport
from codespace.runtime.transport import SSHRoute

HOST_DATA_DIR_NAME = "codespace"
WORKSPACES_DATA_DIR_NAME = "workspaces"
SERVICES_DATA_DIR_NAME = "services"

_DATA_ROOT_TIMEOUT = 15.0
_PREPARE_TIMEOUT = 15.0
_WORKSPACE_LIST_TIMEOUT = 30.0
_HOST_ENVIRONMENT_TIMEOUT = 15.0
_CONTROL_WRITE_TIMEOUT = 15.0


@dataclass(frozen=True, slots=True)
class WorkspacePaths:
    """Absolute host paths owned by one Workspace."""

    root: str
    workspaces_root: str
    workspace: str
    upload: str
    cache: str
    control: str

    def home_cache_mounts(
        self,
        targets: tuple[tuple[str, str], ...],
    ) -> tuple[tuple[str, str], ...]:
        return tuple((f"{self.cache}/{name}", target) for name, target in targets)


@dataclass(frozen=True, slots=True)
class HostDataPaths:
    """Canonical managed data below one Host login home."""

    root: str

    @property
    def workspaces(self) -> str:
        return f"{self.root}/{WORKSPACES_DATA_DIR_NAME}"

    @property
    def services(self) -> str:
        return f"{self.root}/{SERVICES_DATA_DIR_NAME}"

    def workspace(self, project: str, workspace: str) -> WorkspacePaths:
        root = f"{self.workspaces}/{project}/{workspace}"
        return WorkspacePaths(
            root=root,
            workspaces_root=self.workspaces,
            workspace=f"{root}/workspace",
            upload=f"{root}/upload",
            cache=f"{root}/cache",
            control=f"{root}/control",
        )

    def service(self, service: str) -> str:
        return f"{self.services}/{service}"


@cache
def remote_data_paths(route: SSHRoute) -> HostDataPaths:
    command = (
        f'mkdir -p -- "$HOME/{HOST_DATA_DIR_NAME}/{WORKSPACES_DATA_DIR_NAME}" '
        f'"$HOME/{HOST_DATA_DIR_NAME}/{SERVICES_DATA_DIR_NAME}" '
        f'&& printf %s "$HOME/{HOST_DATA_DIR_NAME}"'
    )
    result = transport.run_host(
        route,
        command,
        timeout=_DATA_ROOT_TIMEOUT,
        action="resolve codespace data root",
    )
    root = result.stdout.strip()
    if not root.startswith("/"):
        raise RuntimeError(
            f"host {route.host!r} returned a non-absolute codespace data root: {root!r}"
        )
    return HostDataPaths(root=root)


def prepare_directories(route: SSHRoute, targets: list[str]) -> None:
    if not targets:
        return
    for target in targets:
        if not target.startswith("/"):
            raise RuntimeError(f"refusing to prepare non-absolute path: {target!r}")
    transport.run_host(
        route,
        "mkdir -p -- " + " ".join(shlex.quote(target) for target in targets),
        timeout=_PREPARE_TIMEOUT,
        action=f"prepare directories {targets!r}",
    )


def reset_workspace_control(route: SSHRoute, control_path: str) -> None:
    if not control_path.startswith("/"):
        raise RuntimeError(f"refusing to prepare non-absolute control path: {control_path!r}")
    directory = shlex.quote(control_path)
    provider_ready = shlex.quote(f"{control_path}/provider-ready")
    transport.run_host(
        route,
        f"set -eu; mkdir -p -- {directory}; chmod 0700 -- {directory}; rm -f -- {provider_ready}",
        timeout=_CONTROL_WRITE_TIMEOUT,
        action=f"reset workspace control state in {control_path!r}",
    )


def signal_provider_ready(route: SSHRoute, control_path: str) -> None:
    if not control_path.startswith("/"):
        raise RuntimeError(f"refusing to use non-absolute control path: {control_path!r}")
    marker = shlex.quote(f"{control_path}/provider-ready")
    transport.run_host(
        route,
        f"set -eu; umask 077; : >{marker}",
        timeout=_CONTROL_WRITE_TIMEOUT,
        action=f"authorize workspace bootstrap in {control_path!r}",
    )


def list_workspaces(route: SSHRoute, root: str) -> list[str]:
    """List ``<project>/<workspace>`` directories below the managed root."""
    if not root.startswith("/"):
        raise RuntimeError(f"refusing to list non-absolute workspace root: {root!r}")
    result = transport.run_host(
        route,
        f"find {shlex.quote(root)} -mindepth 2 -maxdepth 2 -type d -print0",
        timeout=_WORKSPACE_LIST_TIMEOUT,
        action=f"list workspaces below {root!r}",
    )
    prefix = root.rstrip("/") + "/"
    paths = [path for path in result.stdout.split("\0") if path]
    if any(not path.startswith(prefix) for path in paths):
        raise RuntimeError(f"host {route.host!r} returned a workspace outside {root!r}")
    return sorted(paths)


def read_environment(route: SSHRoute, names: list[str]) -> dict[str, str]:
    if not names:
        return {}
    result = transport.run_host(
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
