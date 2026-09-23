"""Plan and delete provider deploy keys unused by managed Workspaces."""

from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

import gitlab as python_gitlab
import typer
from github import Auth, Github
from podman import PodmanClient
from rich.console import Console
from rich.table import Column, Table

from codespace import workspaces as inventory
from codespace.config import CONFIG_PATH, load_config
from codespace.resources import RESOURCE_ID_RE
from codespace.workspaces import GitProvider, ProviderSource

_HTTP_TIMEOUT = 30.0
_CLIENT_TIMEOUT = 30 * 60.0

type Repository = tuple[GitProvider, str]
type Route = tuple[str, str]
type Usage = Literal["yes", "no", "unmanaged"]

app = typer.Typer(add_completion=False, no_args_is_help=True)


@dataclass(frozen=True, slots=True)
class DeployKey:
    id: int
    title: str


@app.command("prune")
def _prune(
    apply: Annotated[bool, typer.Option("--apply", help="Delete unused deploy keys.")] = False,
) -> None:
    """Delete provider deploy keys unused by managed Workspaces."""
    prune(apply=apply)


def prune(
    *,
    apply: bool,
    config_path: Path = CONFIG_PATH,
    console: Console | None = None,
) -> None:
    """Inspect and optionally delete unused managed deploy keys."""
    target = console or Console()
    config = load_config(config_path)
    repositories: dict[Repository, list[Route]] = defaultdict(list)
    for project_id, project in config.projects.items():
        if isinstance(project.source, ProviderSource):
            repository = (project.source.type, project.source.repository)
            repositories[repository].extend((host, project_id) for host in project.hosts)

    tokens = config.seed_tokens()
    listable = sorted(repository for repository in repositories if repository[0] in tokens)
    warnings = [
        f"{provider}:{repository}: token is not configured"
        for provider, repository in sorted(repositories)
        if provider not in tokens
    ]
    hosts = sorted(config.hosts)
    with ThreadPoolExecutor() as executor:
        inventories = executor.map(_active_workspace_ids, hosts)
        active = {workspace_id for host_active in inventories for workspace_id in host_active}
        listed = executor.map(
            list_deploy_keys,
            [repository[0] for repository in listable],
            [tokens[repository[0]] for repository in listable],
            [repository[1] for repository in listable],
        )
        keys = dict(zip(listable, listed, strict=True))

    rows: list[tuple[Repository, DeployKey, Usage]] = []
    for repository, deploy_keys in keys.items():
        for key in sorted(deploy_keys, key=lambda item: item.title):
            rows.append((repository, key, _usage(key.title, repositories[repository], active)))
    table = Table(
        Column("Repository", overflow="fold"),
        Column("Deploy key", overflow="fold"),
        Column("In use", no_wrap=True),
    )
    for repository, key, usage in rows:
        table.add_row(f"{repository[0]}:{repository[1]}", key.title, usage)
    target.print(table)
    for warning in warnings:
        target.print(f"[yellow]Warning:[/yellow] {warning}")
    unused = [(repository, key.id) for repository, key, usage in rows if usage == "no"]
    if not apply:
        target.print(f"Dry run: {len(unused)} unused key(s); pass --apply to delete.")
        return
    grouped: dict[Repository, list[int]] = defaultdict(list)
    for repository, key_id in unused:
        grouped[repository].append(key_id)
    targets = sorted(grouped)
    with ThreadPoolExecutor() as executor:
        list(
            executor.map(
                delete_deploy_keys,
                [repository[0] for repository in targets],
                [tokens[repository[0]] for repository in targets],
                [repository[1] for repository in targets],
                [grouped[repository] for repository in targets],
            )
        )
    target.print(f"Deleted {len(unused)} unused key(s).")


def _active_workspace_ids(host: str) -> set[str]:
    with PodmanClient(
        base_url=f"http+ssh://{host}/run/podman/podman.sock",
        timeout=_CLIENT_TIMEOUT,
    ) as client:
        return {workspace.id for workspace in inventory.list_workspaces(client, host)}


def _usage(title: str, routes: list[Route], active: set[str]) -> Usage:
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
            return "no"
    return "unmanaged"


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
