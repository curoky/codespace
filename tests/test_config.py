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
    LABEL_WORKSPACE,
    workspace_identity,
    workspace_ssh_port,
)


def test_default_config_path_is_managed_macos_location() -> None:
    assert str(CONFIG_PATH) == "/Users/x/.config/codespace/config.yaml"


def test_tunnel_ports_default_and_project_override(config: Config) -> None:
    assert config.project_tunnel_ports("codespace") == []
    data = config.model_dump()
    data["project_defaults"]["tunnel_ports"] = [8005, 8080]
    data["projects"]["scratch"]["tunnel_ports"] = []
    data["projects"]["personal"]["tunnel_ports"] = [3000]

    parsed = Config.model_validate(data)

    assert parsed.project_tunnel_ports("codespace") == [8005, 8080]
    assert parsed.project_tunnel_ports("scratch") == []
    assert parsed.project_tunnel_ports("personal") == [3000]


@pytest.mark.parametrize("ports", [[0], [65536], [True], ["8005"], [8005, 8005]])
@pytest.mark.parametrize("scope", ["project_defaults", "project"])
def test_tunnel_ports_reject_invalid_values(
    config: Config, ports: list[object], scope: str
) -> None:
    data = config.model_dump()
    target = (
        data["project_defaults"] if scope == "project_defaults" else data["projects"]["codespace"]
    )
    target["tunnel_ports"] = ports
    with pytest.raises(ValidationError):
        Config.model_validate(data)


def test_example_config_loads() -> None:
    config = load_config(Path("config.example.yaml"))

    assert list(config.projects) == ["codespace"]
    assert list(config.services) == ["support", "vllm", "sglang"]
    assert config.workspace_spec("codespace", "server", "default").identity == (
        "codespace-workspace_server_codespace_default"
    )
    workspace = config.workspace_spec("codespace", "server", "default")
    assert workspace.container.is_bridge
    assert "ATUIN_SYNC_ADDRESS" not in (workspace.container.environment or {})
    assert [(secret.source, secret.mode) for secret in workspace.container.secrets or []] == [
        ("atuin_db_uri", 0o400)
    ]
    support = config.service_spec("support", "server").container
    assert support.is_bridge
    assert not support.ports
    assert not support.secrets
    assert not support.environment
    for service in ("vllm", "sglang"):
        spec = config.service_spec(service, "server")
        assert spec.container.is_bridge
        assert spec.container.ports
        assert all(port.host_ip == "10.88.0.1" for port in spec.container.ports)
        assert (spec.container.environment or {})["SERVE_HOST"] == "0.0.0.0"  # noqa: S104


def test_load_config_rejects_non_mapping(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("- invalid\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must be a mapping"):
        load_config(path)


def test_source_union_and_default_paths(config: Config) -> None:
    managed = config.workspace_spec("codespace", "home", "default")
    direct = config.workspace_spec("personal", "home", "default")
    empty = config.workspace_spec("scratch", "home", "default")

    assert managed.source.model_dump() == {"type": "github", "repository": "curoky/codespace"}
    assert managed.source.clone_url == "git@github.com:curoky/codespace.git"
    assert managed.checkout_path == "/workspace/codespace"
    assert direct.source.model_dump() == {
        "type": "git",
        "url": "git@github.com:curoky/codespace.git",
    }
    assert empty.source.type == "empty"
    assert empty.source.clone_url is None
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


def test_host_rejects_podman_socket_override(config: Config) -> None:
    data = config.model_dump()
    data["hosts"]["home"]["podman_socket"] = "/tmp/podman.sock"

    with pytest.raises(ValidationError, match="Extra inputs"):
        Config.model_validate(data)


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


def test_service_accepts_managed_data_placeholder(config: Config) -> None:
    volumes = config.resolved_service_container("vllm", "office").volumes

    assert volumes is not None
    assert volumes[0].source == "${SERVICE_DATA}"
    assert volumes[0].target == "/root/.cache/huggingface"


def test_service_resolves_data_without_mutating_config(config: Config) -> None:
    data = config.model_dump()
    data["services"]["vllm"]["container"]["volumes"] = [
        "${SERVICE_DATA}:/data:ro",
        "/host/cache:/cache",
        {"type": "bind", "source": "${SERVICE_DATA}", "target": "/models"},
    ]
    configured = Config.model_validate(data)
    spec = configured.service_spec("vllm", "office")

    resolved = spec.resolve_data_path("/home/x/codespace/services/vllm")

    assert [volume.mount() for volume in resolved.volumes or []] == [
        {
            "type": "bind",
            "source": "/home/x/codespace/services/vllm",
            "target": "/data",
            "read_only": True,
        },
        {"type": "bind", "source": "/host/cache", "target": "/cache", "read_only": False},
        {
            "type": "bind",
            "source": "/home/x/codespace/services/vllm",
            "target": "/models",
            "read_only": False,
        },
    ]
    assert [volume.source for volume in spec.container.volumes or []] == [
        "${SERVICE_DATA}",
        "/host/cache",
        "${SERVICE_DATA}",
    ]


@pytest.mark.parametrize("kind, name", [("projects", "scratch"), ("services", "support")])
@pytest.mark.parametrize("source", ["relative", "${OTHER_DATA}", "/${DATA}"])
def test_config_rejects_invalid_mount_sources(
    config: Config, kind: str, name: str, source: str
) -> None:
    data = config.model_dump()
    data[kind][name]["container"] = {
        "network_mode": "host",
        "volumes": [f"{source}:/data"],
    }

    with pytest.raises(ValidationError):
        Config.model_validate(data)


def test_ports_require_bridge_network(config: Config) -> None:
    data = config.model_dump()
    data["projects"]["codespace"]["container"] = {
        "ports": [
            {
                "target": 8080,
                "published": 3000,
                "host_ip": "127.0.0.1",
            }
        ]
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

    home = config.model_dump()
    home["projects"]["codespace"]["container"] = {
        "volumes": ["/tmp/editor:/home/x/.vscode-server/extensions"]
    }
    with pytest.raises(ValidationError, match="overlaps reserved"):
        Config.model_validate(home)

    secret = config.model_dump()
    secret["projects"]["codespace"]["container"] = {
        "secrets": [{"source": "codespace_workspace_key"}]
    }
    with pytest.raises(ValidationError, match="reserved secret"):
        Config.model_validate(secret)


@pytest.mark.parametrize("path", ["/workspace/../etc", "/workspace/repo/../../tmp"])
def test_project_rejects_workspace_path_traversal(config: Config, path: str) -> None:
    data = config.model_dump()
    data["projects"]["codespace"]["open_path"] = path

    with pytest.raises(ValidationError, match="must not contain"):
        Config.model_validate(data)


def test_project_rejects_escaping_derived_checkout_path(config: Config) -> None:
    data = config.model_dump()
    data["projects"]["codespace"]["source"] = {"type": "github", "repository": "owner/.."}

    with pytest.raises(ValidationError, match="must not contain"):
        Config.model_validate(data)


def test_service_data_placeholder_is_rejected_for_projects(config: Config) -> None:
    data = config.model_dump()
    data["projects"]["codespace"]["container"] = {"volumes": ["${SERVICE_DATA}:/workspace/models"]}

    with pytest.raises(ValidationError, match="absolute path"):
        Config.model_validate(data)


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

    assert identity == "codespace-workspace_home_codespace_debug"
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
        "codespace.open-path": "/workspace/codespace",
        "codespace.encrypted": "false",
    }
    assert paths.workspace("codespace", "debug").root == (
        "/home/x/codespace/workspaces/codespace/debug"
    )
    assert paths.service("support") == "/home/x/codespace/services/support"


def test_workspace_identity_has_unambiguous_component_boundaries() -> None:
    assert workspace_identity("home", "a-b", "c") != workspace_identity("home", "a", "b-c")
