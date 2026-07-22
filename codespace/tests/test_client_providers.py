"""Tests for the git provider façade."""

import pytest

from codespace import shared
from codespace.client.providers import provider_client


def test_github_provider_metadata() -> None:
    client = provider_client("github")

    assert client.provider == "github"
    assert client.display_name == "GitHub"


def test_gitlab_provider_metadata() -> None:
    client = provider_client("gitlab")

    assert client.provider == "gitlab"
    assert client.display_name == "GitLab"


def test_provider_client_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="unsupported git provider"):
        provider_client("bitbucket")  # type: ignore[arg-type]


def test_default_git_host_uses_official_hosts() -> None:
    assert shared.default_git_host("github") == "github.com"
    assert shared.default_git_host("gitlab") == "gitlab.com"
