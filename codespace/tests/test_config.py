"""Tests for agent config validation and host-path derivation."""

import pytest

from codespace import shared
from codespace.agent.config import AgentConfig, workspace_host_dir


def test_agent_config_rejects_relative_or_root_workspace() -> None:
    with pytest.raises(ValueError):
        AgentConfig(workspace_root_host="relative", podman_uri="unix:///run/podman/podman.sock")
    with pytest.raises(ValueError):
        AgentConfig(workspace_root_host="/", podman_uri="unix:///run/podman/podman.sock")


def test_agent_config_normalizes_workspace_root() -> None:
    config = AgentConfig(
        workspace_root_host="/var/lib/cs/", podman_uri="unix:///run/podman/podman.sock"
    )
    assert config.workspace_root_host == "/var/lib/cs"


def test_workspace_host_dir_joins_root_and_workspace_name() -> None:
    config = AgentConfig(
        workspace_root_host="/var/lib/cs", podman_uri="unix:///run/podman/podman.sock"
    )
    expected = "/var/lib/cs/" + shared.workspace_dir_name("owner/name", "default", "default")
    assert workspace_host_dir(config, "owner/name", "default", "default") == expected
