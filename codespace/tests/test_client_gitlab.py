"""Tests for the client-side GitLab deploy-key lifecycle (python-gitlab mocked)."""

from typing import ClassVar

import pytest

from codespace.client import gitlab


class _FakeDeployKey:
    def __init__(self, key_id: int, title: str) -> None:
        self.id = key_id
        self.title = title


class _FakeProjectKeys:
    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []
        self.deleted: list[int] = []
        self.existing = [
            _FakeDeployKey(1, "codespace-other"),
            _FakeDeployKey(2, "codespace-abc123"),
        ]

    def create(self, payload: dict[str, object]) -> _FakeDeployKey:
        self.created.append(payload)
        return _FakeDeployKey(42, str(payload["title"]))

    def list(self, *, get_all: bool) -> list[_FakeDeployKey]:
        assert get_all is True
        return self.existing

    def delete(self, key_id: int) -> None:
        self.deleted.append(key_id)


class _FakeProject:
    def __init__(self) -> None:
        self.keys = _FakeProjectKeys()


class _FakeProjects:
    def __init__(self, project: _FakeProject) -> None:
        self.project = project
        self.requested_repo: str | None = None
        self.requested_lazy: bool | None = None

    def get(self, repo: str, *, lazy: bool = False) -> _FakeProject:
        self.requested_repo = repo
        self.requested_lazy = lazy
        return self.project


class _FakeGitlab:
    instances: ClassVar[list["_FakeGitlab"]] = []

    def __init__(self, *, private_token: str, timeout: float) -> None:
        self.private_token = private_token
        self.timeout = timeout
        self.project = _FakeProject()
        self.projects = _FakeProjects(self.project)
        self.instances.append(self)


@pytest.fixture(autouse=True)
def fake_gitlab_client(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeGitlab.instances = []
    monkeypatch.setattr(gitlab.python_gitlab, "Gitlab", _FakeGitlab)


def test_register_deploy_key_uses_gitlab_project_api() -> None:
    key_id = gitlab.register_deploy_key("tok", "group/sub/project", "abc123", "ssh-ed25519 PUB")

    client = _FakeGitlab.instances[0]
    assert key_id == 42
    assert client.private_token == "tok"
    assert client.timeout == gitlab.HTTP_TIMEOUT
    assert client.projects.requested_repo == "group/sub/project"
    assert client.projects.requested_lazy is True
    assert client.project.keys.created == [
        {
            "title": "codespace-abc123",
            "key": "ssh-ed25519 PUB",
            "can_push": True,
        }
    ]


def test_delete_deploy_key_removes_matching_title() -> None:
    removed = gitlab.delete_deploy_key("tok", "group/project", "abc123")

    client = _FakeGitlab.instances[0]
    assert removed is True
    assert client.projects.requested_repo == "group/project"
    assert client.projects.requested_lazy is True
    assert client.project.keys.deleted == [2]


def test_delete_deploy_key_returns_false_when_not_found() -> None:
    client_project = _FakeProject()
    client_project.keys.existing = [_FakeDeployKey(1, "codespace-other")]

    class FakeGitlabWithoutMatchingKey(_FakeGitlab):
        def __init__(self, *, private_token: str, timeout: float) -> None:
            super().__init__(private_token=private_token, timeout=timeout)
            self.project = client_project
            self.projects = _FakeProjects(self.project)

    gitlab.python_gitlab.Gitlab = FakeGitlabWithoutMatchingKey

    removed = gitlab.delete_deploy_key("tok", "group/project", "abc123")

    assert removed is False
    assert client_project.keys.deleted == []
