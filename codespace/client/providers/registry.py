"""Provider-specific deploy-key operations."""

from dataclasses import dataclass
from typing import Protocol

from github import GithubException
from gitlab import GitlabError
from httpx import HTTPError

from codespace import shared
from codespace.client import github
from codespace.client import gitlab as gitlab_client

PROVIDER_ERRORS = (GithubException, GitlabError, HTTPError)


class GitProviderClient(Protocol):
    """Uniform façade for one configured git provider."""

    @property
    def provider(self) -> shared.GitProvider: ...

    @property
    def display_name(self) -> str: ...

    @property
    def config_key(self) -> str: ...

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
    provider: shared.GitProvider = "github"
    display_name: str = "GitHub"
    config_key: str = "github"

    def register_deploy_key(
        self,
        token: str,
        repo: str,
        cs_id: str,
        public_openssh: str,
        *,
        read_only: bool,
    ) -> int:
        return github.register_deploy_key(token, repo, cs_id, public_openssh, read_only=read_only)

    def delete_deploy_key(self, token: str, repo: str, cs_id: str) -> bool:
        return github.delete_deploy_key(token, repo, cs_id)


@dataclass(frozen=True)
class GitlabProviderClient:
    provider: shared.GitProvider = "gitlab"
    display_name: str = "GitLab"
    config_key: str = "gitlab"

    def register_deploy_key(
        self,
        token: str,
        repo: str,
        cs_id: str,
        public_openssh: str,
        *,
        read_only: bool,
    ) -> int:
        return gitlab_client.register_deploy_key(
            token, repo, cs_id, public_openssh, read_only=read_only
        )

    def delete_deploy_key(self, token: str, repo: str, cs_id: str) -> bool:
        return gitlab_client.delete_deploy_key(token, repo, cs_id)


_PROVIDER_CLIENTS: dict[shared.GitProvider, GitProviderClient] = {
    "github": GithubProviderClient(),
    "gitlab": GitlabProviderClient(),
}


def provider_client(provider: shared.GitProvider) -> GitProviderClient:
    """Return a configured façade for ``provider``."""
    try:
        return _PROVIDER_CLIENTS[provider]
    except KeyError as exc:
        raise ValueError(f"unsupported git provider: {provider!r}") from exc
