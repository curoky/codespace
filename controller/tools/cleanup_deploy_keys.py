"""List and optionally delete unused Codespace deploy keys."""

from __future__ import annotations

from collections import defaultdict
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Annotated, Literal

import typer
from rich.console import Console
from rich.table import Table

from controller import inventory, provider
from controller.config import CONFIG_PATH, Config, load_config
from controller.models import RESOURCE_ID_RE, GitProvider
from controller.runtime.transport import PodmanTransport

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

    table = Table()
    table.add_column("Repository", overflow="fold")
    table.add_column("Deploy key", overflow="fold")
    table.add_column("In use", no_wrap=True)
    for (provider_name, repo), key, usage in rows:
        table.add_row(f"{provider_name}:{repo}", key.title, usage)
    console.print(table)

    for error in errors:
        console.print(f"[yellow]Warning:[/yellow] {error}")

    unused = [(repository, key) for repository, key, usage in rows if usage == "no"]
    if not no_dry_run:
        console.print(f"Dry run: {len(unused)} unused key(s); pass --no-dry-run to delete.")
        return

    deleted, delete_errors = _delete(config, unused)
    for error in delete_errors:
        console.print(f"[red]Error:[/red] {error}")
    console.print(f"Deleted {deleted} unused key(s).")


def _repositories(config: Config) -> dict[Repository, list[Route]]:
    repositories: dict[Repository, list[Route]] = defaultdict(list)
    for project_id, project in config.projects.items():
        if project.provider is None or project.repo is None:
            continue
        repository = (project.provider, project.repo)
        repositories[repository].extend((entry.name, project_id) for entry in project.host)
    return repositories


def _collect(
    config: Config,
    repositories: dict[Repository, list[Route]],
) -> tuple[dict[Repository, list[provider.DeployKey]], set[str], set[str], list[str]]:
    keys: dict[Repository, list[provider.DeployKey]] = {}
    active: set[str] = set()
    scanned_hosts: set[str] = set()
    errors: list[str] = []
    transport = PodmanTransport({host: hc.endpoint() for host, hc in config.hosts.items()})
    tokens = config.seed_tokens()

    try:
        with ThreadPoolExecutor() as executor:
            host_futures = {
                executor.submit(_list_inventory, transport, config, host): host
                for host in config.hosts
            }
            repository_futures: dict[Future[list[provider.DeployKey]], Repository] = {}
            for repository in repositories:
                provider_name, repo = repository
                token = tokens.get(provider_name)
                if token is None:
                    errors.append(f"{provider_name}:{repo}: token is not configured")
                    continue
                repository_futures[
                    executor.submit(provider.list_deploy_keys, provider_name, token, repo)
                ] = repository

            for host_future in as_completed(host_futures):
                host = host_futures[host_future]
                try:
                    current = host_future.result()
                except Exception as exc:
                    errors.append(f"{host}: {exc}")
                    continue
                if current.errors:
                    errors.append(f"{host}: {'; '.join(current.errors)}")
                    continue
                scanned_hosts.add(host)
                active.update(environment.id for environment in current.environments)

            for repository_future in as_completed(repository_futures):
                repository = repository_futures[repository_future]
                try:
                    keys[repository] = repository_future.result()
                except Exception as exc:
                    errors.append(f"{repository[0]}:{repository[1]}: {exc}")
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
        for host, project in routes
        if title.startswith(prefix := f"codespace-{host}-{project}-")
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

    errors: list[str] = []
    deleted = 0
    tokens = config.seed_tokens()
    with ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(
                provider.delete_deploy_keys,
                provider_name,
                tokens[provider_name],
                repo,
                key_ids,
            ): (provider_name, repo, len(key_ids))
            for (provider_name, repo), key_ids in grouped.items()
        }
        for future in as_completed(futures):
            provider_name, repo, count = futures[future]
            try:
                future.result()
                deleted += count
            except Exception as exc:
                errors.append(f"{provider_name}:{repo}: {exc}")
    return deleted, errors


if __name__ == "__main__":
    app()
