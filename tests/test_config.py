"""Tests for the final configuration, placement, and identity contracts."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from codespace.config import CONFIG_PATH, Config, load_config
from codespace.runtime.host import HostDataPaths
from codespace.workspaces.models import (
    LABEL_IMAGE,
    LABEL_KIND,
    LABEL_PLATFORM,
    LABEL_PROJECT,
    LABEL_REPOSITORY,
    LABEL_SOURCE,
    LABEL_SSH_PORT,
    LABEL_WORKSPACE,
    workspace_identity,
    workspace_ssh_port,
)


def test_default_config_path_is_xdg_location() -> None:
    assert Path.home() / ".config/codespace/config.yaml" == CONFIG_PATH


def test_example_config_loads() -> None:
    config = load_config(Path("config.example.yaml"))

    assert list(config.projects) == ["codespace"]
    assert list(config.services) == ["support", "vllm", "sglang"]
    assert config.workspace_spec("codespace", "server", "default").identity == (
        "codespace-workspace-server-codespace-default"
    )


def test_load_config_rejects_non_mapping(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("- invalid\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must be a mapping"):
        load_config(path)


def test_source_union_and_default_paths(config: Config) -> None:
    managed = config.workspace_spec("codespace", "home", "default")
    direct = config.workspace_spec("personal", "home", "default")
    empty = config.workspace_spec("scratch", "home", "default")

    assert managed.source == "github"
    assert managed.repository == "curoky/codespace"
    assert managed.clone_url == "git@github.com:curoky/codespace.git"
    assert managed.checkout_path == "/workspace/codespace"
    assert direct.source == "git"
    assert direct.git_url == "git@github.com:curoky/codespace.git"
    assert empty.source == "empty"
    assert empty.clone_url is None
    assert empty.checkout_path == "/workspace"


@pytest.mark.parametrize(
    "source",
    [
        {"type": "github", "repository": "owner/repo"},
        {"type": "gitlab", "repository": "group/repo"},
        {"type": "git", "url": "git@example.com:owner/repo.git"},
        {"type": "empty"},
    ],
)
def test_all_source_variants_are_canonical(config: Config, source: dict[str, str]) -> None:
    data = config.model_dump()
    data["projects"]["scratch"]["source"] = source

    parsed = Config.model_validate(data)

    assert parsed.projects["scratch"].source.type == source["type"]


@pytest.mark.parametrize("unknown", [{"unexpected": {}}, {"extra": "value"}])
def test_config_rejects_unknown_top_level_fields(
    config: Config,
    unknown: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        Config.model_validate({**config.model_dump(), **unknown})


def test_project_layers_apply_host_defaults_and_replace_mappings(config: Config) -> None:
    data = config.model_dump()
    data["hosts"]["home"]["container"] = {
        "environment": {"HOST": "1"},
        "devices": ["/dev/fuse"],
        "pids_limit": 64,
    }
    data["projects"]["codespace"]["container"] = {
        "environment": {"PROJECT": "1"},
        "cap_add": ["NET_RAW"],
    }
    data["projects"]["codespace"]["hosts"]["home"]["container"] = {
        "environment": {"PLACEMENT": "1"},
        "pids_limit": 128,
    }
    data["projects"]["codespace"]["hosts"]["home"]["image"] = "workspace:placement"

    parsed = Config.model_validate(data)
    resolved = parsed.resolved_project_container("codespace", "home")

    assert resolved.environment == {"PLACEMENT": "1"}
    assert resolved.devices == ["/dev/fuse"]
    assert resolved.cap_add == ["NET_RAW"]
    assert resolved.pids_limit == 128
    assert parsed.project_image("codespace", "home") == "workspace:placement"


def test_project_placement_platform_overrides_host_default(config: Config) -> None:
    data = config.model_dump()
    data["projects"]["codespace"]["hosts"]["home"]["platform"] = "linux/amd64"

    parsed = Config.model_validate(data)

    assert parsed.project_platform("codespace", "home") == "linux/amd64"
    assert parsed.workspace_spec("codespace", "home", "default").platform == "linux/amd64"


def test_service_layers_apply_host_defaults_before_service(config: Config) -> None:
    data = config.model_dump()
    data["hosts"]["home"]["container"] = {
        "devices": ["/dev/fuse"],
        "pids_limit": 64,
    }
    data["services"]["support"]["container"]["environment"] = {"BASE": "1"}
    data["services"]["support"]["hosts"]["home"] = {
        "image": "support:pinned",
        "container": {"environment": {"PLACEMENT": "1"}, "network_mode": "bridge"},
    }

    parsed = Config.model_validate(data)
    resolved = parsed.resolved_service_container("support", "home")

    assert parsed.service_image("support", "home") == "support:pinned"
    assert resolved.environment == {"PLACEMENT": "1"}
    assert resolved.devices == ["/dev/fuse"]
    assert resolved.pids_limit == 64


def test_config_accepts_compose_volume_short_syntax(config: Config) -> None:
    data = config.model_dump()
    data["project_defaults"]["container"]["volumes"] = ["/host/path:/opt/data:ro"]

    parsed = Config.model_validate(data)

    assert parsed.project_defaults.container.volumes is not None
    assert parsed.project_defaults.container.volumes[0].source == "/host/path"
    assert parsed.project_defaults.container.volumes[0].read_only is True


def test_ports_require_bridge_network(config: Config) -> None:
    data = config.model_dump()
    data["projects"]["codespace"]["container"] = {
        "ports": {"web": {"host": 3000, "container": 8080}}
    }

    with pytest.raises(ValidationError, match="only in bridge mode"):
        Config.model_validate(data)


def test_project_rejects_reserved_environment_and_mounts(config: Config) -> None:
    environment = config.model_dump()
    environment["projects"]["codespace"]["container"] = {
        "environment": {"CODESPACE_SOURCE_TYPE": "empty"}
    }
    with pytest.raises(ValidationError, match="reserved environment"):
        Config.model_validate(environment)

    volume = config.model_dump()
    volume["projects"]["codespace"]["container"] = {
        "volumes": [
            {
                "type": "bind",
                "source": "/host/data",
                "target": "/workspace/generated",
            }
        ]
    }
    with pytest.raises(ValidationError, match="overlaps reserved"):
        Config.model_validate(volume)


def test_unknown_host_reference_is_rejected(config: Config) -> None:
    data = config.model_dump()
    data["projects"]["codespace"]["hosts"] = {"missing": {}}

    with pytest.raises(ValidationError, match="unknown host"):
        Config.model_validate(data)


def test_encrypted_project_requires_syncable_key(config: Config) -> None:
    data = config.model_dump()
    data["projects"]["codespace"]["encrypted"] = True

    with pytest.raises(ValidationError, match="codespace_workspace_key"):
        Config.model_validate(data)

    data["secrets"]["codespace_workspace_key"] = "test-key"
    assert Config.model_validate(data).projects["codespace"].encrypted is True


def test_tokens_are_seeded_without_leaking_from_repr(config: Config) -> None:
    data = config.model_dump()
    data["tokens"] = {"github": "ghp_example"}

    parsed = Config.model_validate(data)

    assert parsed.seed_tokens() == {"github": "ghp_example"}
    assert "ghp_example" not in repr(parsed)


def test_workspace_identity_labels_and_paths(config: Config) -> None:
    identity = workspace_identity("home", "codespace", "debug")
    spec = config.workspace_spec("codespace", "home", "debug")
    paths = HostDataPaths("/home/x/codespace")

    assert identity == "codespace-workspace-home-codespace-debug"
    assert spec.identity == identity
    assert 20_000 <= workspace_ssh_port(identity) <= 29_999
    assert spec.labels() == {
        LABEL_KIND: "workspace",
        LABEL_PROJECT: "codespace",
        LABEL_WORKSPACE: "debug",
        LABEL_SOURCE: "github",
        LABEL_REPOSITORY: "curoky/codespace",
        LABEL_IMAGE: "ghcr.io/curoky/codespace:workspace-debian13",
        LABEL_PLATFORM: "linux/arm64",
        LABEL_SSH_PORT: str(spec.ssh_port),
    }
    assert paths.workspace("codespace", "debug").root == (
        "/home/x/codespace/workspaces/codespace/debug"
    )
    assert paths.service("support") == "/home/x/codespace/services/support"
