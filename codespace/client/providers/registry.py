"""Provider-specific deploy-key operations."""

from typing import Protocol

from github import GithubException
from gitlab import GitlabError
from httpx import HTTPError
from pydantic import BaseModel, ConfigDict

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


class GithubProviderClient(BaseModel):
    model_config = ConfigDict(frozen=True)

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
        return github.register_deploy_key(
            token, repo, cs_id, public_openssh, read_only=read_only
        )

    def delete_deploy_key(self, token: str, repo: str, cs_id: str) -> bool:
        return github.delete_deploy_key(token, repo, cs_id)


class GitlabProviderClient(BaseModel):
    model_config = ConfigDict(frozen=True)

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


def provider_client(provider: shared.GitProvider) -> GitProviderClient:
    """Return a configured façade for ``provider``."""
    match provider:
        case "github":
            return GithubProviderClient()
        case "gitlab":
            return GitlabProviderClient()
