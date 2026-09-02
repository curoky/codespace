"""GitHub and GitLab deploy-key lifecycle without a provider registry."""

from __future__ import annotations

from dataclasses import dataclass

import gitlab as python_gitlab
from github import Auth, Github

from controller.models import GitProvider

_HTTP_TIMEOUT = 30.0


@dataclass(frozen=True, slots=True)
class DeployKey:
    """Provider-neutral deploy key metadata used by maintenance tools."""

    id: int
    title: str


def register(
    provider: GitProvider,
    token: str,
    repo: str,
    title: str,
    public_key: str,
) -> int:
    """Replace matching deploy keys and register one read-write key."""
    match provider:
        case "github":
            with Github(auth=Auth.Token(token)) as github:
                repository = github.get_repo(repo)
                for github_key in repository.get_keys():
                    if github_key.title == title:
                        github_key.delete()
                created_github_key = repository.create_key(
                    title=title,
                    key=public_key,
                    read_only=False,
                )
                return int(created_github_key.id)
        case "gitlab":
            gitlab = python_gitlab.Gitlab(
                private_token=token,
                timeout=_HTTP_TIMEOUT,
            )
            project = gitlab.projects.get(repo, lazy=True)
            for gitlab_key in project.keys.list(get_all=True):
                if gitlab_key.title == title:
                    project.keys.delete(gitlab_key.id)
            created_gitlab_key = project.keys.create(
                {
                    "title": title,
                    "key": public_key,
                    "can_push": True,
                }
            )
            return int(created_gitlab_key.id)


def revoke(
    provider: GitProvider,
    token: str,
    repo: str,
    title: str,
) -> int:
    """Delete every deploy key with the deterministic environment title."""
    removed = 0
    match provider:
        case "github":
            with Github(auth=Auth.Token(token)) as github:
                repository = github.get_repo(repo)
                for github_key in repository.get_keys():
                    if github_key.title == title:
                        github_key.delete()
                        removed += 1
        case "gitlab":
            gitlab = python_gitlab.Gitlab(
                private_token=token,
                timeout=_HTTP_TIMEOUT,
            )
            project = gitlab.projects.get(repo, lazy=True)
            for gitlab_key in project.keys.list(get_all=True):
                if gitlab_key.title == title:
                    project.keys.delete(gitlab_key.id)
                    removed += 1
    return removed


def list_deploy_keys(
    provider: GitProvider,
    token: str,
    repo: str,
) -> list[DeployKey]:
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
            gitlab = python_gitlab.Gitlab(
                private_token=token,
                timeout=_HTTP_TIMEOUT,
            )
            project = gitlab.projects.get(repo, lazy=True)
            return [
                DeployKey(id=int(gitlab_key.id), title=str(gitlab_key.title))
                for gitlab_key in project.keys.list(get_all=True)
            ]


def delete_deploy_keys(
    provider: GitProvider,
    token: str,
    repo: str,
    key_ids: list[int],
) -> None:
    """Delete deploy keys by provider ID from one repository."""
    match provider:
        case "github":
            with Github(auth=Auth.Token(token)) as github:
                repository = github.get_repo(repo)
                for key_id in key_ids:
                    repository.get_key(key_id).delete()
        case "gitlab":
            gitlab = python_gitlab.Gitlab(
                private_token=token,
                timeout=_HTTP_TIMEOUT,
            )
            project = gitlab.projects.get(repo, lazy=True)
            for key_id in key_ids:
                project.keys.delete(key_id)
