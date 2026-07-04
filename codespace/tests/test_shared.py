"""Tests for the shared protocol models and helpers."""

import pytest
from pydantic import ValidationError

from codespace import shared


def test_repo_slug_replaces_slash() -> None:
    assert shared.repo_slug("owner/name") == "owner-name"


def test_container_name_has_prefix() -> None:
    assert shared.container_name("abc123") == "codespace-abc123"


def test_workspace_dir_name_is_stable_and_deterministic() -> None:
    first = shared.workspace_dir_name("owner/name", "default", "default")
    second = shared.workspace_dir_name("owner/name", "default", "default")
    assert first == second
    assert first.startswith("codespace-owner-name-default-default-")


def test_workspace_dir_name_disambiguates_colliding_slugs() -> None:
    # ``a/b-c`` and ``a-b/c`` slug-collide to ``a-b-c``; the hash suffix must differ.
    one = shared.workspace_dir_name("a/b-c", "default", "default")
    two = shared.workspace_dir_name("a-b/c", "default", "default")
    assert one != two


@pytest.mark.parametrize("repo", ["owner/name", "o.w-n/re_po", "a1/b2"])
def test_create_request_accepts_valid_repo(repo: str) -> None:
    req = shared.CreateRequest(
        repo=repo, login_pubkey="ssh-ed25519 AAAA", image="codespace/dev:latest"
    )
    assert req.repo == repo
    assert req.template == shared.DEFAULT_TEMPLATE
    assert req.instance == shared.DEFAULT_INSTANCE


@pytest.mark.parametrize("repo", ["noslash", "too/many/parts", "bad repo/name", ""])
def test_create_request_rejects_invalid_repo(repo: str) -> None:
    with pytest.raises(ValidationError):
        shared.CreateRequest(
            repo=repo, login_pubkey="ssh-ed25519 AAAA", image="codespace/dev:latest"
        )


def test_create_request_rejects_blank_image() -> None:
    with pytest.raises(ValidationError):
        shared.CreateRequest(repo="owner/name", login_pubkey="ssh-ed25519 AAAA", image="  ")


def test_create_request_requires_image() -> None:
    with pytest.raises(ValidationError):
        shared.CreateRequest(repo="owner/name", login_pubkey="ssh-ed25519 AAAA")


@pytest.mark.parametrize("field", ["workspace", "user", "extra_repos", "alias"])
def test_create_request_rejects_removed_client_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        shared.CreateRequest(
            repo="owner/name",
            login_pubkey="ssh-ed25519 AAAA",
            image="codespace/dev:latest",
            **{field: "removed"},
        )


def test_deploy_key_title_uses_prefix() -> None:
    assert shared.deploy_key_title("abc123") == "codespace-abc123"


@pytest.mark.parametrize("field", ["template", "instance"])
def test_create_request_rejects_invalid_template_instance_names(field: str) -> None:
    with pytest.raises(ValidationError):
        shared.CreateRequest(
            repo="owner/name",
            login_pubkey="ssh-ed25519 AAAA",
            image="codespace/dev:latest",
            **{field: "bad name"},
        )
