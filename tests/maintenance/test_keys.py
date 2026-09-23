"""Tests for unused deploy-key classification."""

from __future__ import annotations

from io import StringIO
from typing import ClassVar

import pytest
from rich.console import Console

from codespace.config import Config
from codespace.maintenance import keys
from codespace.maintenance.keys import DeployKey


@pytest.mark.parametrize(
    ("title", "active", "expected"),
    [
        (
            "space:codespace/live@home",
            {"space:codespace/live@home"},
            "yes",
        ),
        ("space:codespace/old@home", set(), "no"),
        ("space:codespace/live@office", set(), "no"),
        ("manual-key", set(), "unmanaged"),
        ("space:other/live@home", set(), "unmanaged"),
        ("space:codespace/live@unknown", set(), "unmanaged"),
        ("space:codespace/invalid/name@home", set(), "unmanaged"),
        ("space:codespace/@home", set(), "unmanaged"),
    ],
)
def test_usage(
    title: str,
    active: set[str],
    expected: str,
) -> None:
    routes = [("home", "codespace"), ("office", "codespace")]

    assert keys._usage(title, routes, active) == expected


class FakePodmanClient:
    def __init__(self, host: str) -> None:
        self.host = host
        self.closed = False

    def __enter__(self) -> FakePodmanClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.closed = True


@pytest.mark.parametrize("apply", [False, True])
def test_prune_deletes_only_planned_unused_keys(
    config: Config, monkeypatch: pytest.MonkeyPatch, apply: bool
) -> None:
    data = config.model_dump()
    data["tokens"] = {"github": "test-token"}
    configured = Config.model_validate(data)
    active = configured.workspace_spec("codespace", "home", "live").to_workspace(
        "container-id", status="running"
    )
    listed = [
        DeployKey(1, active.id),
        DeployKey(2, "space:codespace/old@home"),
        DeployKey(3, "manual-key"),
    ]
    deleted: list[list[int]] = []
    clients: list[FakePodmanClient] = []
    options: list[dict[str, object]] = []

    def create_client(**kwargs: object) -> FakePodmanClient:
        host = str(kwargs["base_url"]).removeprefix("http+ssh://").partition("/")[0]
        client = FakePodmanClient(host)
        clients.append(client)
        options.append(kwargs)
        return client

    monkeypatch.setattr(keys, "load_config", lambda _path: configured)
    monkeypatch.setattr(keys, "PodmanClient", create_client)
    monkeypatch.setattr(keys.inventory, "list_workspaces", lambda *_args: [active])
    monkeypatch.setattr(keys, "list_deploy_keys", lambda *_args: listed)
    monkeypatch.setattr(
        keys,
        "delete_deploy_keys",
        lambda _provider, _token, _repo, ids: deleted.append(ids),
    )

    keys.prune(apply=apply, console=Console(file=StringIO(), width=120))

    assert deleted == ([[2]] if apply else [])
    assert all(client.closed for client in clients)
    assert {option["timeout"] for option in options} == {keys._CLIENT_TIMEOUT}


def test_prune_fails_before_listing_keys_when_host_scan_fails(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = config.model_dump()
    data["tokens"] = {"github": "test-token"}
    configured = Config.model_validate(data)
    listed = False

    def active_workspace_ids(host: str) -> set[str]:
        if host == "office":
            raise RuntimeError("scan failed")
        return set()

    def list_keys(*_args: object) -> list[DeployKey]:
        nonlocal listed
        listed = True
        return []

    monkeypatch.setattr(keys, "load_config", lambda _path: configured)
    monkeypatch.setattr(keys, "_active_workspace_ids", active_workspace_ids)
    monkeypatch.setattr(keys, "list_deploy_keys", list_keys)
    stream = StringIO()

    with pytest.raises(RuntimeError, match="scan failed"):
        keys.prune(apply=False, console=Console(file=stream, width=120))

    assert listed is False
    assert stream.getvalue() == ""


def test_prune_warns_and_skips_repository_without_token(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = Config.model_validate({**config.model_dump(), "tokens": {}})
    listed = False

    def list_keys(*_args: object) -> list[DeployKey]:
        nonlocal listed
        listed = True
        return []

    monkeypatch.setattr(keys, "load_config", lambda _path: configured)
    monkeypatch.setattr(keys, "_active_workspace_ids", lambda _host: set())
    monkeypatch.setattr(keys, "list_deploy_keys", list_keys)
    stream = StringIO()

    keys.prune(apply=False, console=Console(file=stream, width=120))

    assert listed is False
    assert "token is not configured" in stream.getvalue()


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
            GithubKey("space:codespace/debug@home", 1),
            GithubKey("space:codespace/debug@home", 2),
            GithubKey("other", 3),
        ]

    def get_keys(self) -> list[GithubKey]:
        return self.keys

    def get_key(self, key_id: int) -> GithubKey:
        return next(key for key in self.keys if key.id == key_id)


class GithubClient:
    def __init__(self, repo: GithubRepo) -> None:
        self.repo = repo

    def __enter__(self) -> GithubClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def get_repo(self, _repo: str) -> GithubRepo:
        return self.repo


class GitlabKey:
    def __init__(self, key_id: int, title: str) -> None:
        self.id = key_id
        self.title = title


class GitlabKeys:
    def __init__(self) -> None:
        self.existing = [
            GitlabKey(1, "space:service-api/debug@office"),
            GitlabKey(2, "space:service-api/debug@office"),
        ]
        self.deleted: list[int] = []

    def list(self, *, get_all: bool) -> list[GitlabKey]:
        assert get_all is True
        return self.existing

    def delete(self, key_id: int) -> None:
        self.deleted.append(key_id)


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


def test_github_list_and_delete_deploy_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = GithubRepo()
    monkeypatch.setattr(keys.Auth, "Token", lambda token: token)
    monkeypatch.setattr(keys, "Github", lambda auth: GithubClient(repo))

    assert keys.list_deploy_keys("github", "token", "owner/repo") == [
        DeployKey(1, "space:codespace/debug@home"),
        DeployKey(2, "space:codespace/debug@home"),
        DeployKey(3, "other"),
    ]

    keys.delete_deploy_keys("github", "token", "owner/repo", [2, 3])

    assert [key.deleted for key in repo.keys] == [False, True, True]


def test_gitlab_list_and_delete_deploy_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    GitlabClient.instances = []
    monkeypatch.setattr(keys.python_gitlab, "Gitlab", GitlabClient)

    assert keys.list_deploy_keys("gitlab", "token", "group/service-api") == [
        DeployKey(1, "space:service-api/debug@office"),
        DeployKey(2, "space:service-api/debug@office"),
    ]

    keys.delete_deploy_keys("gitlab", "token", "group/service-api", [1, 2])

    assert GitlabClient.instances[1].project.keys.deleted == [1, 2]
