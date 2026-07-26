"""Tests for direct GitHub and GitLab deploy-key dispatch."""

from __future__ import annotations

from typing import ClassVar

import pytest

from codespace.client import provider


class GithubKey:
    def __init__(self, title: str, key_id: int) -> None:
        self.title = title
        self.id = key_id
        self.deleted = False

    def delete(self) -> None:
        self.deleted = True


class GithubRepo:
    def __init__(self) -> None:
        self.keys = [
            GithubKey("codespace-home-devspace-debug", 1),
            GithubKey("codespace-home-devspace-debug", 2),
            GithubKey("other", 3),
        ]
        self.created: dict[str, object] | None = None

    def get_keys(self) -> list[GithubKey]:
        return self.keys

    def create_key(self, *, title: str, key: str, read_only: bool) -> GithubKey:
        self.created = {"title": title, "key": key, "read_only": read_only}
        return GithubKey(title, 9)


class GithubClient:
    def __init__(self, repo: GithubRepo) -> None:
        self.repo = repo

    def __enter__(self) -> GithubClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def get_repo(self, _repo: str) -> GithubRepo:
        return self.repo


def test_github_register_replaces_all_matching_titles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = GithubRepo()
    monkeypatch.setattr(provider.Auth, "Token", lambda token: token)
    monkeypatch.setattr(provider, "Github", lambda auth: GithubClient(repo))

    key_id = provider.register(
        "github",
        "token",
        "curoky/devspace",
        "codespace-home-devspace-debug",
        "ssh-ed25519 PUBLIC",
    )

    assert key_id == 9
    assert [key.deleted for key in repo.keys] == [True, True, False]
    assert repo.created == {
        "title": "codespace-home-devspace-debug",
        "key": "ssh-ed25519 PUBLIC",
        "read_only": False,
    }


class GitlabKey:
    def __init__(self, key_id: int, title: str) -> None:
        self.id = key_id
        self.title = title


class GitlabKeys:
    def __init__(self) -> None:
        self.existing = [
            GitlabKey(1, "codespace-office-service-api-debug"),
            GitlabKey(2, "codespace-office-service-api-debug"),
        ]
        self.deleted: list[int] = []
        self.created: list[dict[str, object]] = []

    def list(self, *, get_all: bool) -> list[GitlabKey]:
        assert get_all is True
        return self.existing

    def delete(self, key_id: int) -> None:
        self.deleted.append(key_id)

    def create(self, payload: dict[str, object]) -> GitlabKey:
        self.created.append(payload)
        return GitlabKey(7, str(payload["title"]))


class GitlabProject:
    def __init__(self) -> None:
        self.keys = GitlabKeys()


class GitlabClient:
    instances: ClassVar[list[GitlabClient]] = []

    def __init__(self, *, private_token: str, timeout: float) -> None:
        self.private_token = private_token
        self.timeout = timeout
        self.project = GitlabProject()
        self.projects = type(
            "Projects",
            (),
            {"get": lambda _self, _repo, lazy: self.project if lazy else None},
        )()
        self.instances.append(self)


def test_gitlab_register_replaces_all_matching_titles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    GitlabClient.instances = []
    monkeypatch.setattr(provider.python_gitlab, "Gitlab", GitlabClient)

    key_id = provider.register(
        "gitlab",
        "token",
        "group/service-api",
        "codespace-office-service-api-debug",
        "ssh-ed25519 PUBLIC",
    )

    client = GitlabClient.instances[0]
    assert key_id == 7
    assert client.project.keys.deleted == [1, 2]
    assert client.project.keys.created == [
        {
            "title": "codespace-office-service-api-debug",
            "key": "ssh-ed25519 PUBLIC",
            "can_push": True,
        }
    ]


def test_revoke_missing_key_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = GithubRepo()
    repo.keys = [GithubKey("other", 3)]
    monkeypatch.setattr(provider.Auth, "Token", lambda token: token)
    monkeypatch.setattr(provider, "Github", lambda auth: GithubClient(repo))

    assert provider.revoke("github", "token", "owner/repo", "missing") == 0
