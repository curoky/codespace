"""Shared protocol models and constants for the codespace client and agent.

This module is the single source of truth for the wire contract between the
local client and the Linux agent. Both sides import from here.
"""

import hashlib
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

type CreateOperationStatus = Literal["queued", "running", "succeeded", "failed"]
type GitProvider = Literal["github", "gitlab"]

# --- Constants ---------------------------------------------------------------

# Container name prefix; scopes every podman operation the agent performs.
CONTAINER_PREFIX = "codespace-"

# Default login user inside the dev container (see DESIGN.md §3 image contract).
# The reference dev image (codespace/images/dev) ships a pre-created login user `x` (uid 5230).
DEFAULT_CONTAINER_USER = "x"

# Workspace mount point inside the dev container.
WORKSPACE_MOUNT = "/workspace"

# Label keys stored on the dev container; the agent is stateless and reads all
# persistent metadata back from these labels. GitHub metadata (deploy key id)
# is intentionally NOT stored here: the client owns all GitHub interaction and
# rediscovers keys by title (see ``deploy_key_title``), so the agent never
# touches GitHub or holds a token.
LABEL_ID = "codespace.id"
LABEL_REPO = "codespace.repo"
LABEL_PROVIDER = "codespace.provider"
LABEL_TEMPLATE = "codespace.template"
LABEL_INSTANCE = "codespace.instance"
LABEL_IMAGE = "codespace.image"
LABEL_PORT = "codespace.port"

# Validation patterns.
REPO_RE = re.compile(r"^[\w.-]+(?:/[\w.-]+)+$")
WORKSPACE_RE = re.compile(r"^[\w.-]+$")
DEFAULT_GIT_PROVIDER: GitProvider = "github"
DEFAULT_GITHUB_SSH_HOST = "github.com"
DEFAULT_GITLAB_SSH_HOST = "gitlab.com"
DEFAULT_TEMPLATE = "default"
DEFAULT_INSTANCE = "default"


# --- Helpers -----------------------------------------------------------------


def repo_slug(repo: str) -> str:
    """Convert ``owner/name`` into a filesystem-friendly slug."""
    return repo.replace("/", "-")


def workspace_dir_name(repo: str, template: str, instance: str) -> str:
    """Compute the host workspace directory name for a repo/template/instance tuple.

    A short hash suffix disambiguates slugs that would otherwise collide
    (e.g. ``a/b-c`` vs ``a-b/c``). See DESIGN.md §7.
    """
    digest = hashlib.sha256(f"{repo}\0{template}\0{instance}".encode()).hexdigest()[:8]
    return f"{CONTAINER_PREFIX}{repo_slug(repo)}-{template}-{instance}-{digest}"


def container_name(cs_id: str) -> str:
    """Container name for a codespace id."""
    return f"{CONTAINER_PREFIX}{cs_id}"


def deploy_key_title(cs_id: str) -> str:
    """GitHub deploy key title for a codespace id.

    ``cs_id`` is the single cross-system correlation key: it lives on the
    container label and in this key title, so the client can rediscover and
    delete a codespace's deploy key by title without persisting its id.
    """
    return f"{CONTAINER_PREFIX}{cs_id}"


def default_git_host(provider: GitProvider) -> str:
    """Return the official SSH host for a supported git provider."""
    match provider:
        case "github":
            return DEFAULT_GITHUB_SSH_HOST
        case "gitlab":
            return DEFAULT_GITLAB_SSH_HOST


# --- Wire models -------------------------------------------------------------


class CreateRequest(BaseModel):
    """POST /codespaces request body.

    The client owns all GitHub interaction, so no token is sent to the agent.
    ``image`` is supplied by the client; the agent fixes the login user and
    uses ``template``/``instance`` only for remote resource identity.
    """

    model_config = ConfigDict(extra="forbid")

    repo: str = Field(..., description="Target repo path, e.g. 'owner/name'.")
    provider: GitProvider = Field(
        DEFAULT_GIT_PROVIDER, description="Git provider hosting the repo."
    )
    template: str = Field(DEFAULT_TEMPLATE, description="Template id for this instance.")
    instance: str = Field(DEFAULT_INSTANCE, description="Instance name under the template.")
    login_pubkey: str = Field(..., description="Client SSH public key for login.")
    image: str = Field(..., description="Dev image satisfying the DESIGN.md §3 contract.")

    @field_validator("repo")
    @classmethod
    def _check_repo(cls, v: str) -> str:
        if not REPO_RE.match(v):
            raise ValueError("repo must be a slash-separated path like 'owner/name'")
        return v

    @field_validator("template", "instance")
    @classmethod
    def _check_name(cls, v: str) -> str:
        if not WORKSPACE_RE.match(v):
            raise ValueError("must match [\\w.-]+")
        return v

    @field_validator("login_pubkey", "image")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v


class Codespace(BaseModel):
    """A managed codespace, returned by create/list.

    ``deploy_public_key`` is only populated by ``create``: the agent generates
    the repo deploy keypair, keeps the private half (injected into the
    container) and hands the public half back so the client can register it as
    a provider deploy key. It is ``None`` for ``list`` results.

    The SSH host is *not* included: the agent only reports the ``port`` it can
    observe from podman; the client supplies the reachable host itself (it is
    the client-side view of where the host is).
    """

    id: str
    port: int
    user: str
    container_id: str
    repo: str
    provider: GitProvider = DEFAULT_GIT_PROVIDER
    template: str = DEFAULT_TEMPLATE
    instance: str = DEFAULT_INSTANCE
    workspace_dir: str
    deploy_public_key: str | None = None
    status: str | None = None


class CreateOperation(BaseModel):
    """Status for an asynchronous codespace creation operation."""

    id: str
    status: CreateOperationStatus
    stage: str
    codespace: Codespace | None = None
    error: str | None = None


class DeleteResponse(BaseModel):
    ok: bool = True
    workspace_removed: bool = False


class CloneRepoResponse(BaseModel):
    ok: bool = True


class ErrorResponse(BaseModel):
    error: str
