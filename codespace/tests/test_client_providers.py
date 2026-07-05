"""Tests for the git provider façade."""

import pytest

from codespace import shared
from codespace.client.config import (
    DefaultsConfig,
    GithubConfig,
    GitlabConfig,
    WebConfig,
)
from codespace.client.providers import provider_client


def _config() -> WebConfig:
    return WebConfig(
        defaults=DefaultsConfig(agent="home", image="img"),
        github=GithubConfig(token_env="GH_TOKEN"),
        gitlab=GitlabConfig(
            token_env="GL_TOKEN",
            api_url="https://gitlab.example.com",
            ssh_host="gitlab.example.com",
        ),
        agents={"home": {"agent_url": "http://h:8001", "ssh_host": "10.0.0.5"}},
    )


def test_github_provider_reads_env_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "secret")

    client = provider_client(_config(), "github")

    assert client.provider == "github"
    assert client.display_name == "GitHub"
    assert client.token == "secret"
    assert client.token_label == "GH_TOKEN"
    assert client.ssh_host == shared.DEFAULT_GITHUB_SSH_HOST


def test_gitlab_provider_uses_configured_api_and_ssh_host() -> None:
    client = provider_client(_config(), "gitlab")

    assert client.provider == "gitlab"
    assert client.display_name == "GitLab"
    assert client.token is None
    assert client.token_label == "GL_TOKEN"
    assert client.ssh_host == "gitlab.example.com"
