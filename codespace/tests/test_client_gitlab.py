"""Tests for the client-side GitLab deploy-key lifecycle (httpx mocked)."""

import httpx
import pytest

from codespace.client import gitlab


class _FakeResponse:
    def __init__(self, data: object) -> None:
        self._data = data

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._data


def test_register_deploy_key_uses_gitlab_project_api(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def _post(url: str, **kwargs: object) -> _FakeResponse:
        calls.append({"url": url, **kwargs})
        return _FakeResponse({"id": 42})

    monkeypatch.setattr(httpx, "post", _post)

    key_id = gitlab.register_deploy_key(
        "tok", "https://gitlab.example.com", "group/sub/project", "abc123", "ssh-ed25519 PUB"
    )

    assert key_id == 42
    assert calls == [
        {
            "url": "https://gitlab.example.com/api/v4/projects/group%2Fsub%2Fproject/deploy_keys",
            "headers": {"PRIVATE-TOKEN": "tok"},
            "json": {
                "title": "codespace-abc123",
                "key": "ssh-ed25519 PUB",
                "can_push": True,
            },
            "timeout": gitlab.HTTP_TIMEOUT,
        }
    ]


def test_delete_deploy_key_removes_matching_title(monkeypatch: pytest.MonkeyPatch) -> None:
    deleted: list[str] = []

    def _get(url: str, **kwargs: object) -> _FakeResponse:
        assert url == "https://gitlab.com/api/v4/projects/group%2Fproject/deploy_keys"
        assert kwargs["headers"] == {"PRIVATE-TOKEN": "tok"}
        return _FakeResponse(
            [
                {"id": 1, "title": "codespace-other"},
                {"id": 2, "title": "codespace-abc123"},
            ]
        )

    def _delete(url: str, **kwargs: object) -> _FakeResponse:
        deleted.append(url)
        assert kwargs["headers"] == {"PRIVATE-TOKEN": "tok"}
        return _FakeResponse({})

    monkeypatch.setattr(httpx, "get", _get)
    monkeypatch.setattr(httpx, "delete", _delete)

    removed = gitlab.delete_deploy_key("tok", "https://gitlab.com", "group/project", "abc123")

    assert removed is True
    assert deleted == ["https://gitlab.com/api/v4/projects/group%2Fproject/deploy_keys/2"]
