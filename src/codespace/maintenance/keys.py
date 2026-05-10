"""Plan and delete provider deploy keys unused by managed Workspaces."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Literal

from rich.console import Console

from codespace.config import CONFIG_PATH, Config, ProviderSource, load_config
from codespace.maintenance import output
from codespace.runtime.transport import PodmanTransport
from codespace.workspaces import inventory, provider
from codespace.workspaces.models import RESOURCE_ID_RE, GitProvider

type Repository = tuple[GitProvider, str]
type Route = tuple[str, str]
type Usage = Literal["yes", "no", "unknown", "unmanaged"]


def prune(
    *,
    apply: bool,
    config_path: Path = CONFIG_PATH,
    console: Console | None = None,
) -> None:
    """Show unused managed deploy keys, then optionally delete them."""
    target = console or Console()
    config = load_config(config_path)
    repositories = _repositories(config)
    keys, active, scanned_hosts, errors = _collect(config, repositories)
    rows: list[tuple[Repository, provider.DeployKey, Usage]] = []
    for repository, deploy_keys in sorted(keys.items()):
        for key in sorted(deploy_keys, key=lambda item: item.title):
            rows.append(
                (
                    repository,
                    key,
                    _usage(key.title, repositories[repository], active, scanned_hosts),
                )
            )
    output.render_table(
        target,
        [
            {"header": "Repository", "overflow": "fold"},
            {"header": "Deploy key", "overflow": "fold"},
            {"header": "In use", "no_wrap": True},
        ],
        [
            (f"{provider_name}:{repository}", key.title, usage)
            for (provider_name, repository), key, usage in rows
        ],
    )
    output.print_warnings(target, errors)
    unused = [(repository, key) for repository, key, usage in rows if usage == "no"]
    if not apply:
        target.print(f"Dry run: {len(unused)} unused key(s); pass --apply to delete.")
        return
    deleted, delete_errors = _delete(config, unused)
    output.print_errors(target, delete_errors)
    target.print(f"Deleted {deleted} unused key(s).")


def _repositories(config: Config) -> dict[Repository, list[Route]]:
    repositories: dict[Repository, list[Route]] = defaultdict(list)
    for project_id, project in config.projects.items():
        if not isinstance(project.source, ProviderSource):
            continue
        repository = (project.source.type, project.source.repository)
        repositories[repository].extend((host, project_id) for host in project.hosts)
    return repositories


def _collect(
    config: Config,
    repositories: dict[Repository, list[Route]],
) -> tuple[dict[Repository, list[provider.DeployKey]], set[str], set[str], list[str]]:
    active: set[str] = set()
    scanned_hosts: set[str] = set()
    errors: list[str] = []
    transport = PodmanTransport({host: value.endpoint() for host, value in config.hosts.items()})
    tokens = config.seed_tokens()
    try:
        inventories, host_failures = output.fan_out(
            config.hosts,
            lambda host: inventory.list_workspaces(transport.client(host), host),
        )
        for host, workspaces in inventories:
            scanned_hosts.add(host)
            active.update(workspace.id for workspace in workspaces)
        errors.extend(f"{host}: {exc}" for host, exc in host_failures)

        listable = [
            repository for repository in repositories if tokens.get(repository[0]) is not None
        ]
        errors.extend(
            f"{provider_name}:{repository}: token is not configured"
            for provider_name, repository in repositories
            if tokens.get(provider_name) is None
        )
        listed, key_failures = output.fan_out(
            listable,
            lambda repository: provider.list_deploy_keys(
                repository[0],
                tokens[repository[0]],
                repository[1],
            ),
        )
        keys = dict(listed)
        errors.extend(f"{repository[0]}:{repository[1]}: {exc}" for repository, exc in key_failures)
    finally:
        transport.close()
    return keys, active, scanned_hosts, errors


def _usage(title: str, routes: list[Route], active: set[str], scanned_hosts: set[str]) -> Usage:
    if not title.startswith("codespace-workspace-"):
        return "unmanaged"
    if title in active:
        return "yes"
    matching_hosts = {
        host
        for host, project in routes
        if title.startswith(prefix := f"codespace-workspace-{host}-{project}-")
        and RESOURCE_ID_RE.fullmatch(title.removeprefix(prefix))
    }
    return "unknown" if matching_hosts - scanned_hosts else "no"


def _delete(
    config: Config,
    unused: list[tuple[Repository, provider.DeployKey]],
) -> tuple[int, list[str]]:
    grouped: dict[Repository, list[int]] = defaultdict(list)
    for repository, key in unused:
        grouped[repository].append(key.id)
    tokens = config.seed_tokens()
    _results, failures = output.fan_out(
        grouped,
        lambda repository: provider.delete_deploy_keys(
            repository[0],
            tokens[repository[0]],
            repository[1],
            grouped[repository],
        ),
    )
    deleted = sum(len(grouped[repository]) for repository in grouped) - sum(
        len(grouped[repository]) for repository, _exc in failures
    )
    errors = [f"{repository[0]}:{repository[1]}: {exc}" for repository, exc in failures]
    return deleted, errors
