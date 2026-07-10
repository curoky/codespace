"""Agent runtime configuration and host-path derivation.

Only host-environment properties live here; caller-side choices (image, login
user, reachable SSH host) are supplied by the client. Values come from the
``serve`` CLI. See DESIGN.md §6.
"""

import posixpath

from pydantic import BaseModel, Field, field_validator

from codespace import shared


class AgentConfig(BaseModel):
    """Agent runtime configuration, validated at startup (fail-fast)."""

    workspace_root_host: str = Field(..., description="Host path prefix for workspace bind mounts.")
    podman_uri: str = Field(..., description="Podman service socket URI.")

    @field_validator("workspace_root_host")
    @classmethod
    def _validate_workspace_root_host(cls, value: str) -> str:
        root = posixpath.normpath(value.strip())
        if not root.startswith("/") or root == "/":
            raise ValueError("workspace_root_host must be an absolute non-root host path")
        return root


def workspace_host_dir(config: AgentConfig, repo: str, template: str, instance: str) -> str:
    """Compute the host workspace directory path passed to podman's bind source."""
    name = shared.workspace_dir_name(repo, template, instance)
    return posixpath.join(config.workspace_root_host, name)
