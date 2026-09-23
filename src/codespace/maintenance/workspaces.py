"""Plan and delete Workspace data without a matching managed container."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

import typer
from podman import PodmanClient
from rich.console import Console
from rich.table import Column, Table

from codespace import workspaces as inventory
from codespace.config import CONFIG_PATH, load_config
from codespace.resources import RESOURCE_ID_RE
from codespace.runtime import container, host
from codespace.runtime.transport import SSHRoute

_CLIENT_TIMEOUT = 30 * 60.0

type Usage = Literal["yes", "no", "unmanaged"]

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command("prune")
def _prune(
    apply: Annotated[bool, typer.Option("--apply", help="Delete unused Workspace data.")] = False,
) -> None:
    """Delete Workspace data without a matching managed container."""
    prune(apply=apply)


def prune(
    *,
    apply: bool,
    config_path: Path = CONFIG_PATH,
    console: Console | None = None,
) -> None:
    """Inspect and optionally delete orphan Workspace directories."""
    target = console or Console()
    config = load_config(config_path)
    hosts = sorted(config.hosts)
    images = [config.workspace_helper_image(host_name) for host_name in hosts]
    with ThreadPoolExecutor() as executor:
        scans = executor.map(
            partial(_prune_host, apply=apply),
            hosts,
            images,
        )
        states = [
            (host_name, path, usage)
            for host_name, host_states in zip(hosts, scans, strict=True)
            for path, usage in host_states
        ]

    table = Table(
        "Host",
        Column("Workspace", overflow="fold"),
        Column("In use", no_wrap=True),
    )
    for host_name, path, usage in states:
        table.add_row(host_name, path, usage)
    target.print(table)

    unused = sum(state[2] == "no" for state in states)
    if apply:
        target.print(f"Deleted {unused} unused Workspace(s).")
    else:
        target.print(f"Dry run: {unused} unused Workspace(s); pass --apply to delete.")


def _prune_host(
    host_name: str,
    image: str,
    *,
    apply: bool,
) -> list[tuple[str, Usage]]:
    route = SSHRoute(host_name)
    data_paths = host.remote_data_paths(route)
    root = data_paths.workspaces
    scanned = host.list_workspaces(route, root)
    with PodmanClient(
        base_url=f"http+ssh://{host_name}/run/podman/podman.sock",
        timeout=_CLIENT_TIMEOUT,
    ) as client:
        active = {
            data_paths.workspace(workspace.project, workspace.workspace)
            for workspace in inventory.list_workspaces(client, host_name)
        }
        states = [(path, _usage(root, path, active)) for path in scanned]
        if apply:
            for path, usage in states:
                if usage == "no":
                    container.remove_data_directory(client, image, root, path)
    return states


def _usage(root: str, path: str, active: set[str]) -> Usage:
    try:
        relative = PurePosixPath(path).relative_to(PurePosixPath(root))
    except ValueError:
        return "unmanaged"
    if len(relative.parts) != 2 or any(
        not RESOURCE_ID_RE.fullmatch(part) for part in relative.parts
    ):
        return "unmanaged"
    return "yes" if path in active else "no"


if __name__ == "__main__":
    app()
