"""List and optionally delete unused Codespace deploy keys."""

from __future__ import annotations

from collections import defaultdict
from typing import Annotated, Literal

import typer
from rich.console import Console

from controller import inventory, provider
from controller.config import CONFIG_PATH, Config, RepoWorkspace, load_config
from controller.models import RESOURCE_ID_RE, GitProvider
from controller.tools import support
from controller.transport import PodmanTransport

type Repository = tuple[GitProvider, str]
type Route = tuple[str, str]
type Usage = Literal["yes", "no", "unknown", "unmanaged"]

app = typer.Typer(add_completion=False)
console = Console()


@app.command()
def main(
    no_dry_run: Annotated[
        bool,
        typer.Option("--no-dry-run", help="Delete unused Codespace deploy keys."),
    ] = False,
) -> None:
    """Show deploy keys for configured repositories and whether they are in use."""
    config = load_config(CONFIG_PATH)
    repositories = _repositories(config)
    keys, active, scanned_hosts, errors = _collect(config, repositories)

    rows: list[tuple[Repository, provider.DeployKey, Usage]] = []
    for repository, deploy_keys in sorted(keys.items()):
        for key in sorted(deploy_keys, key=lambda item: item.title):
            usage = _usage(key.title, repositories[repository], active, scanned_hosts)
            rows.append((repository, key, usage))

    support.render_table(
        console,
        [
            {"header": "Repository", "overflow": "fold"},
            {"header": "Deploy key", "overflow": "fold"},
            {"header": "In use", "no_wrap": True},
        ],
        [
            (f"{provider_name}:{repo}", key.title, usage)
            for (provider_name, repo), key, usage in rows
        ],
    )
    support.print_warnings(console, errors)

    unused = [(repository, key) for repository, key, usage in rows if usage == "no"]
    if not no_dry_run:
        console.print(f"Dry run: {len(unused)} unused key(s); pass --no-dry-run to delete.")
        return

    deleted, delete_errors = _delete(config, unused)
    support.print_errors(console, delete_errors)
    console.print(f"Deleted {deleted} unused key(s).")


def _repositories(config: Config) -> dict[Repository, list[Route]]:
    repositories: dict[Repository, list[Route]] = defaultdict(list)
    for workspace_id, ws in config.workspaces.items.items():
        if not isinstance(ws, RepoWorkspace):
            continue
        repository = (ws.provider, ws.repo)
        repositories[repository].extend((entry.name, workspace_id) for entry in ws.host)
    return repositories


def _collect(
    config: Config,
    repositories: dict[Repository, list[Route]],
) -> tuple[dict[Repository, list[provider.DeployKey]], set[str], set[str], list[str]]:
    active: set[str] = set()
    scanned_hosts: set[str] = set()
    errors: list[str] = []
    transport = PodmanTransport({host: hc.endpoint() for host, hc in config.hosts.items()})
    tokens = config.seed_tokens()

    try:
        inventories, host_failures = support.fan_out(
            config.hosts, lambda host: _list_inventory(transport, config, host)
        )
        for host, current in inventories:
            if current.errors:
                errors.append(f"{host}: {'; '.join(current.errors)}")
                continue
            scanned_hosts.add(host)
            active.update(environment.id for environment in current.environments)
        errors.extend(f"{host}: {exc}" for host, exc in host_failures)

        listable = [
            repository for repository in repositories if tokens.get(repository[0]) is not None
        ]
        errors.extend(
            f"{provider_name}:{repo}: token is not configured"
            for provider_name, repo in repositories
            if tokens.get(provider_name) is None
        )
        listed, key_failures = support.fan_out(
            listable,
            lambda repository: provider.list_deploy_keys(
                repository[0], tokens[repository[0]], repository[1]
            ),
        )
        keys = dict(listed)
        errors.extend(f"{repository[0]}:{repository[1]}: {exc}" for repository, exc in key_failures)
    finally:
        transport.close()
    return keys, active, scanned_hosts, errors


def _list_inventory(transport: PodmanTransport, config: Config, host: str) -> inventory.Inventory:
    return inventory.list_inventory(transport.client(host), host, config)


def _usage(title: str, routes: list[Route], active: set[str], scanned_hosts: set[str]) -> Usage:
    if not title.startswith("codespace-"):
        return "unmanaged"
    if title in active:
        return "yes"
    matching_hosts = {
        host
        for host, workspace in routes
        if title.startswith(prefix := f"codespace-{host}-{workspace}-")
        and RESOURCE_ID_RE.fullmatch(title.removeprefix(prefix))
    }
    if matching_hosts - scanned_hosts:
        return "unknown"
    return "no"


def _delete(
    config: Config,
    unused: list[tuple[Repository, provider.DeployKey]],
) -> tuple[int, list[str]]:
    grouped: dict[Repository, list[int]] = defaultdict(list)
    for repository, key in unused:
        grouped[repository].append(key.id)

    tokens = config.seed_tokens()
    _results, failures = support.fan_out(
        grouped,
        lambda repository: provider.delete_deploy_keys(
            repository[0], tokens[repository[0]], repository[1], grouped[repository]
        ),
    )
    deleted = sum(len(grouped[repository]) for repository in grouped) - sum(
        len(grouped[repository]) for repository, _exc in failures
    )
    errors = [f"{repository[0]}:{repository[1]}: {exc}" for repository, exc in failures]
    return deleted, errors


if __name__ == "__main__":
    app()
