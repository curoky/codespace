"""List and optionally delete workspaces without managed containers."""

from __future__ import annotations

from collections import defaultdict
from pathlib import PurePosixPath
from typing import Annotated, Literal

import typer
from rich.console import Console

from controller import container, inventory, ssh
from controller.config import CONFIG_PATH, Config, load_config
from controller.models import RESOURCE_ID_RE
from controller.tools import support
from controller.transport import PodmanTransport

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
    transport = PodmanTransport({host: hc.endpoint() for host, hc in config.hosts.items()})
    try:
        workspaces, errors = _collect(config, transport)
        rows = [
            (host, root, path, _usage(root, path, active))
            for host, root, path, active in workspaces
        ]

        support.render_table(
            console,
            [
                {"header": "Host"},
                {"header": "Workspace", "overflow": "fold"},
                {"header": "In use", "no_wrap": True},
            ],
            [(host, path, usage) for host, _root, path, usage in rows],
        )
        support.print_warnings(console, errors)

        unused = [(host, root, path) for host, root, path, usage in rows if usage == "no"]
        if not no_dry_run:
            console.print(
                f"Dry run: {len(unused)} unused workspace(s); pass --no-dry-run to delete."
            )
            return

        deleted, delete_errors = _delete(config, transport, unused)
        support.print_errors(console, delete_errors)
        console.print(f"Deleted {deleted} unused workspace(s).")
    finally:
        transport.close()


def _collect(
    config: Config,
    transport: PodmanTransport,
) -> tuple[list[tuple[str, str, str, set[str]]], list[str]]:
    scanned_by_host, failures = support.fan_out(
        config.hosts, lambda host: _scan_host(config, transport, host)
    )
    workspaces = [
        (host, root, path, active)
        for host, (scanned, active) in scanned_by_host
        for root, path in scanned
    ]
    workspaces.sort(key=lambda item: (item[0], item[2]))
    return workspaces, [f"{host}: {exc}" for host, exc in failures]


def _scan_host(
    config: Config,
    transport: PodmanTransport,
    host: str,
) -> tuple[list[tuple[str, str]], set[str]]:
    client = transport.client(host)
    route = transport.ssh_route(host)
    current = inventory.list_inventory(client, host, config)
    if current.errors:
        raise RuntimeError("; ".join(current.errors))
    data_paths = ssh.remote_data_paths(route)
    root = data_paths.workspaces
    scanned = [(root, path) for path in ssh.list_instances(route, root)]
    active = {
        data_paths.instance(environment.workspace, environment.instance).root
        for environment in current.environments
    }
    return scanned, active


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

    results, _failures = support.fan_out(
        grouped,
        lambda host: _delete_host(transport, host, config.workspaces.defaults.image, grouped[host]),
    )
    deleted = 0
    errors: list[str] = []
    for host, (host_deleted, host_errors) in results:
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
            container.remove_data_directory(client, image, root, path)
            deleted += 1
        except Exception as exc:  # a per-workspace failure surfaces in the report
            errors.append(f"{path}: {exc}")
    return deleted, errors


if __name__ == "__main__":
    app()
