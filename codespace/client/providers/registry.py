"""Provider-specific token, SSH host and deploy-key operations."""

import os
from dataclasses import dataclass
from typing import Protocol

from github import GithubException
from httpx import HTTPError

from codespace import shared
from codespace.client import github, gitlab
from codespace.client.config import WebConfig

PROVIDER_ERRORS = (GithubException, HTTPError)


class GitProviderClient(Protocol):
    """Uniform façade for one configured git provider."""

    @property
    def provider(self) -> shared.GitProvider: ...

    @property
    def display_name(self) -> str: ...

    @property
    def config_key(self) -> str: ...

    @property
    def token_env(self) -> str: ...

    @property
    def token_label(self) -> str: ...

    @property
    def ssh_host(self) -> str: ...

    @property
    def token(self) -> str | None:
        """Return the configured provider token, if available."""

    def register_deploy_key(
        self,
        token: str,
        repo: str,
        cs_id: str,
        public_openssh: str,
        *,
        read_only: bool,
    ) -> int:
        """Register a deploy key for one repository."""

    def delete_deploy_key(self, token: str, repo: str, cs_id: str) -> bool:
        """Delete a deploy key for one repository."""


@dataclass(frozen=True)
class GithubProviderClient:
    token_env: str = "GITHUB_TOKEN"  # noqa: S105 - env var name, not a token

    provider: shared.GitProvider = "github"
    display_name: str = "GitHub"
    config_key: str = "github"
    ssh_host: str = shared.DEFAULT_GITHUB_SSH_HOST

    @property
    def token(self) -> str | None:
        return os.environ.get(self.token_env)

    @property
    def token_label(self) -> str:
        return self.token_env

    def register_deploy_key(
        self,
        token: str,
        repo: str,
        cs_id: str,
        public_openssh: str,
        *,
        read_only: bool,
    ) -> int:
        return github.register_deploy_key(
            token, repo, cs_id, public_openssh, read_only=read_only
        )

    def delete_deploy_key(self, token: str, repo: str, cs_id: str) -> bool:
        return github.delete_deploy_key(token, repo, cs_id)


@dataclass(frozen=True)
class GitlabProviderClient:
    token_env: str = "GITLAB_TOKEN"  # noqa: S105 - env var name, not a token
    api_url: str = "https://gitlab.com"
    ssh_host: str = shared.DEFAULT_GITLAB_SSH_HOST

    provider: shared.GitProvider = "gitlab"
    display_name: str = "GitLab"
    config_key: str = "gitlab"

    @property
    def token(self) -> str | None:
        return os.environ.get(self.token_env)

    @property
    def token_label(self) -> str:
        return self.token_env

    def register_deploy_key(
        self,
        token: str,
        repo: str,
        cs_id: str,
        public_openssh: str,
        *,
        read_only: bool,
    ) -> int:
        return gitlab.register_deploy_key(
            token, self.api_url, repo, cs_id, public_openssh, read_only=read_only
        )

    def delete_deploy_key(self, token: str, repo: str, cs_id: str) -> bool:
        return gitlab.delete_deploy_key(token, self.api_url, repo, cs_id)


def provider_client(
    config: WebConfig | None, provider: shared.GitProvider
) -> GitProviderClient:
    """Return a configured façade for ``provider``."""
    match provider:
        case "github":
            return GithubProviderClient(
                token_env=config.github.token_env if config is not None else "GITHUB_TOKEN"
            )
        case "gitlab":
            return GitlabProviderClient(
                token_env=config.gitlab.token_env if config is not None else "GITLAB_TOKEN",
                api_url=config.gitlab.api_url if config is not None else "https://gitlab.com",
                ssh_host=(
                    config.gitlab.ssh_host
                    if config is not None
                    else shared.DEFAULT_GITLAB_SSH_HOST
                ),
            )
