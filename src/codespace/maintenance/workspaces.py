"""Plan and delete Workspace data without a matching managed container."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
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
from codespace.runtime.transport import PodmanTransport, SSHRoute

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
    images = {host_name: config.workspace_helper_image(host_name) for host_name in hosts}
    with (
        closing(PodmanTransport(hosts, client_timeout=_CLIENT_TIMEOUT)) as transport,
        ThreadPoolExecutor() as executor,
    ):

        def scan_host(host_name: str) -> tuple[str, list[tuple[str, Usage]]]:
            return _scan_host(transport.client(host_name), transport.ssh_route(host_name))

        plans = list(executor.map(scan_host, hosts))
        states = [
            (host_name, path, usage)
            for host_name, (_root, scanned) in zip(hosts, plans, strict=True)
            for path, usage in scanned
        ]

        table = Table(
            "Host",
            Column("Workspace", overflow="fold"),
            Column("In use", no_wrap=True),
        )
        for host_name, path, usage in states:
            table.add_row(host_name, path, usage)
        target.print(table)
        if apply:

            def apply_host(host_name: str, plan: tuple[str, list[tuple[str, Usage]]]) -> None:
                root, scanned = plan
                client = transport.client(host_name)
                for path, usage in scanned:
                    if usage == "no":
                        container.remove_data_directory(client, images[host_name], root, path)

            list(executor.map(apply_host, hosts, plans))

    unused = sum(state[2] == "no" for state in states)
    if apply:
        target.print(f"Deleted {unused} unused Workspace(s).")
    else:
        target.print(f"Dry run: {unused} unused Workspace(s); pass --apply to delete.")


def _scan_host(
    client: PodmanClient,
    route: SSHRoute,
) -> tuple[str, list[tuple[str, Usage]]]:
    data_paths = host.remote_data_paths(route)
    root = data_paths.workspaces
    scanned = host.list_workspaces(route, root)
    active = {
        data_paths.workspace(workspace.project, workspace.workspace)
        for workspace in inventory.list_workspaces(client, route.host)
    }
    return root, [(path, _usage(root, path, active)) for path in scanned]


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
