"""Tests for the client-side GitHub deploy-key lifecycle (PyGithub mocked)."""

import pytest

from codespace.client import github


class _FakeKey:
    def __init__(self, title: str, key_id: int) -> None:
        self.title = title
        self.id = key_id
        self.deleted = False

    def delete(self) -> None:
        self.deleted = True


class _FakeRepo:
    def __init__(self, keys: list[_FakeKey] | None = None) -> None:
        self.keys = keys or []
        self.created: dict | None = None

    def create_key(self, title: str, key: str, read_only: bool) -> _FakeKey:
        created = _FakeKey(title=title, key_id=999)
        self.created = {"title": title, "key": key, "read_only": read_only}
        self.keys.append(created)
        return created

    def get_keys(self) -> list[_FakeKey]:
        return self.keys


class _FakeGithub:
    def __init__(self, repo: _FakeRepo) -> None:
        self._repo = repo

    def __enter__(self) -> "_FakeGithub":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def get_repo(self, _repo: str) -> _FakeRepo:
        return self._repo


@pytest.fixture(autouse=True)
def _patch_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    # Auth.Token is called but its result is only fed to the (patched) Github.
    monkeypatch.setattr(github.Auth, "Token", lambda token: token)


def test_register_deploy_key_creates_titled_readwrite_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _FakeRepo()
    monkeypatch.setattr(github, "Github", lambda auth: _FakeGithub(repo))

    key_id = github.register_deploy_key("tok", "owner/name", "abc123", "ssh-ed25519 PUB")

    assert key_id == 999
    assert repo.created == {
        "title": "codespace-abc123",
        "key": "ssh-ed25519 PUB",
        "read_only": False,
    }


def test_delete_deploy_key_removes_matching_title(monkeypatch: pytest.MonkeyPatch) -> None:
    match = _FakeKey(title="codespace-abc123", key_id=1)
    other = _FakeKey(title="codespace-zzz999", key_id=2)
    repo = _FakeRepo(keys=[match, other])
    monkeypatch.setattr(github, "Github", lambda auth: _FakeGithub(repo))

    removed = github.delete_deploy_key("tok", "owner/name", "abc123")

    assert removed is True
    assert match.deleted is True
    assert other.deleted is False


def test_delete_deploy_key_absent_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _FakeRepo(keys=[_FakeKey(title="codespace-other", key_id=1)])
    monkeypatch.setattr(github, "Github", lambda auth: _FakeGithub(repo))

    removed = github.delete_deploy_key("tok", "owner/name", "abc123")

    assert removed is False
