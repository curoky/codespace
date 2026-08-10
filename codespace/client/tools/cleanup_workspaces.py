"""List and optionally delete workspaces without managed containers."""

from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import PurePosixPath
from typing import Annotated, Literal

import typer
from rich.console import Console
from rich.table import Table

from codespace.client import container, inventory, ssh
from codespace.client.config import CONFIG_PATH, Config, load_config
from codespace.client.models import RESOURCE_ID_RE
from codespace.client.transport import PodmanTransport

type Usage = Literal["yes", "no", "unmanaged"]
type Workspace = tuple[str, str, str]

app = typer.Typer(add_completion=False)
console = Console()


@app.command()
def main(
    no_dry_run: Annotated[
        bool,
        typer.Option("--no-dry-run", help="Delete workspaces without managed containers."),
    ] = False,
) -> None:
    """Show host workspace directories and whether they have managed containers."""
    config = load_config(CONFIG_PATH)
    transport = PodmanTransport(config.hosts)
    try:
        workspaces, errors = _collect(config, transport)
        rows = [
            (host, root, path, _usage(root, path, active))
            for host, root, path, active in workspaces
        ]

        table = Table()
        table.add_column("Host")
        table.add_column("Workspace", overflow="fold")
        table.add_column("In use", no_wrap=True)
        for host, _root, path, usage in rows:
            table.add_row(host, path, usage)
        console.print(table)

        for error in errors:
            console.print(f"[yellow]Warning:[/yellow] {error}")

        unused = [(host, root, path) for host, root, path, usage in rows if usage == "no"]
        if not no_dry_run:
            console.print(
                f"Dry run: {len(unused)} unused workspace(s); pass --no-dry-run to delete."
            )
            return

        deleted, delete_errors = _delete(config, transport, unused)
        for error in delete_errors:
            console.print(f"[red]Error:[/red] {error}")
        console.print(f"Deleted {deleted} unused workspace(s).")
    finally:
        transport.close()


def _collect(
    config: Config,
    transport: PodmanTransport,
) -> tuple[list[tuple[str, str, str, set[str]]], list[str]]:
    workspaces: list[tuple[str, str, str, set[str]]] = []
    errors: list[str] = []
    with ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(_scan_host, config, transport, host): host for host in config.hosts
        }
        for future in as_completed(futures):
            host = futures[future]
            try:
                root, paths, active = future.result()
            except Exception as exc:
                errors.append(f"{host}: {exc}")
                continue
            workspaces.extend((host, root, path, active) for path in paths)
    workspaces.sort(key=lambda item: (item[0], item[2]))
    return workspaces, errors


def _scan_host(
    config: Config,
    transport: PodmanTransport,
    host: str,
) -> tuple[str, list[str], set[str]]:
    client = transport.client(host)
    route = transport.ssh_route(host)
    current = inventory.list_inventory(client, host, config)
    if current.errors:
        raise RuntimeError("; ".join(current.errors))
    root = ssh.remote_workspace_root(route)
    paths = ssh.list_workspaces(route, root)
    active = {
        f"{root}/{environment.project}/{environment.instance}"
        for environment in current.environments
    }
    return root, paths, active


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


def _delete(
    config: Config,
    transport: PodmanTransport,
    workspaces: list[Workspace],
) -> tuple[int, list[str]]:
    grouped: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for host, root, path in workspaces:
        grouped[host].append((root, path))

    deleted = 0
    errors: list[str] = []
    with ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(
                _delete_host,
                transport,
                host,
                config.default_image,
                paths,
            ): host
            for host, paths in grouped.items()
        }
        for future in as_completed(futures):
            host = futures[future]
            host_deleted, host_errors = future.result()
            deleted += host_deleted
            errors.extend(f"{host}: {error}" for error in host_errors)
    return deleted, errors


def _delete_host(
    transport: PodmanTransport,
    host: str,
    image: str,
    workspaces: list[tuple[str, str]],
) -> tuple[int, list[str]]:
    client = transport.client(host)
    deleted = 0
    errors: list[str] = []
    for root, path in workspaces:
        try:
            container.remove_workspace(client, image, root, path)
            deleted += 1
        except Exception as exc:
            errors.append(f"{path}: {exc}")
    return deleted, errors


if __name__ == "__main__":
    app()
