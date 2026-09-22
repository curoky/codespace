"""Plan and delete provider deploy keys unused by managed Workspaces."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

import gitlab as python_gitlab
import typer
from github import Auth, Github
from rich.console import Console
from rich.table import Column, Table

from codespace import workspaces as inventory
from codespace.config import CONFIG_PATH, Config, load_config
from codespace.resources import RESOURCE_ID_RE
from codespace.runtime.transport import PodmanTransport
from codespace.workspaces import GitProvider, ProviderSource

_HTTP_TIMEOUT = 30.0

type Repository = tuple[GitProvider, str]
type Route = tuple[str, str]
type Usage = Literal["yes", "no", "unknown", "unmanaged"]

app = typer.Typer(add_completion=False, no_args_is_help=True)


@dataclass(frozen=True, slots=True)
class DeployKey:
    id: int
    title: str


@dataclass(frozen=True, slots=True)
class KeyCandidate:
    repository: Repository
    key: DeployKey
    usage: Usage


@app.command("prune")
def _prune(
    apply: Annotated[bool, typer.Option("--apply", help="Apply the displayed plan.")] = False,
) -> None:
    """Delete provider deploy keys unused by managed Workspaces."""
    prune(apply=apply)


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
    rows: list[KeyCandidate] = []
    for repository, deploy_keys in sorted(keys.items()):
        for key in sorted(deploy_keys, key=lambda item: item.title):
            rows.append(
                KeyCandidate(
                    repository,
                    key,
                    _usage(key.title, repositories[repository], active, scanned_hosts),
                )
            )
    table = Table(
        Column("Repository", overflow="fold"),
        Column("Deploy key", overflow="fold"),
        Column("In use", no_wrap=True),
    )
    for item in rows:
        table.add_row(f"{item.repository[0]}:{item.repository[1]}", item.key.title, item.usage)
    target.print(table)
    for error in errors:
        target.print(f"[yellow]Warning:[/yellow] {error}")
    unused = [item for item in rows if item.usage == "no"]
    if not apply:
        target.print(f"Dry run: {len(unused)} unused key(s); pass --apply to delete.")
        return
    deleted, delete_errors = _delete(config.seed_tokens(), unused)
    for error in delete_errors:
        target.print(f"[red]Error:[/red] {error}")
    target.print(f"Deleted {deleted} unused key(s).")


def _fan_out[K, V](
    keys: Iterable[K], work: Callable[[K], V]
) -> tuple[list[tuple[K, V]], list[tuple[K, Exception]]]:
    """Run all planned targets, retaining each target's success or failure."""
    results: list[tuple[K, V]] = []
    failures: list[tuple[K, Exception]] = []
    with ThreadPoolExecutor() as executor:
        futures = {executor.submit(work, key): key for key in keys}
        for future in as_completed(futures):
            key = futures[future]
            try:
                results.append((key, future.result()))
            except Exception as exc:
                failures.append((key, exc))
    return results, failures


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
) -> tuple[dict[Repository, list[DeployKey]], set[str], set[str], list[str]]:
    active: set[str] = set()
    scanned_hosts: set[str] = set()
    errors: list[str] = []
    transport = PodmanTransport(config.hosts)
    tokens = config.seed_tokens()
    try:
        inventories, host_failures = _fan_out(
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
        listed, key_failures = _fan_out(
            listable,
            lambda repository: list_deploy_keys(
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
    if title in active:
        return "yes"
    for host, project in routes:
        prefix = f"space:{project}/"
        suffix = f"@{host}"
        if (
            title.startswith(prefix)
            and title.endswith(suffix)
            and RESOURCE_ID_RE.fullmatch(title.removeprefix(prefix).removesuffix(suffix))
        ):
            return "no" if host in scanned_hosts else "unknown"
    return "unmanaged"


def _delete(
    tokens: dict[GitProvider, str],
    unused: list[KeyCandidate],
) -> tuple[int, list[str]]:
    grouped: dict[Repository, list[int]] = defaultdict(list)
    for item in unused:
        grouped[item.repository].append(item.key.id)
    _results, failures = _fan_out(
        grouped,
        lambda repository: delete_deploy_keys(
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


def list_deploy_keys(provider: GitProvider, token: str, repo: str) -> list[DeployKey]:
    """List deploy keys attached to one repository."""
    match provider:
        case "github":
            with Github(auth=Auth.Token(token)) as github:
                repository = github.get_repo(repo)
                return [
                    DeployKey(id=int(github_key.id), title=str(github_key.title))
                    for github_key in repository.get_keys()
                ]
        case "gitlab":
            gitlab = python_gitlab.Gitlab(private_token=token, timeout=_HTTP_TIMEOUT)
            project = gitlab.projects.get(repo, lazy=True)
            return [
                DeployKey(id=int(gitlab_key.id), title=str(gitlab_key.title))
                for gitlab_key in project.keys.list(get_all=True)
            ]


def delete_deploy_keys(provider: GitProvider, token: str, repo: str, key_ids: list[int]) -> None:
    """Delete deploy keys by provider ID from one repository."""
    match provider:
        case "github":
            with Github(auth=Auth.Token(token)) as github:
                repository = github.get_repo(repo)
                for key_id in key_ids:
                    repository.get_key(key_id).delete()
        case "gitlab":
            gitlab = python_gitlab.Gitlab(private_token=token, timeout=_HTTP_TIMEOUT)
            project = gitlab.projects.get(repo, lazy=True)
            for key_id in key_ids:
                project.keys.delete(key_id)


if __name__ == "__main__":
    app()
