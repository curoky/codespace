"""Tests for the final configuration, placement, and identity contracts."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from codespace.config import CONFIG_PATH, Config, load_config
from codespace.resources import LABEL_IMAGE, LABEL_KIND, Resource
from codespace.runtime.host import HostDataPaths
from codespace.workspaces import (
    LABEL_PLATFORM,
    LABEL_PROJECT,
    LABEL_REPOSITORY,
    LABEL_SOURCE,
    LABEL_WORKSPACE,
    workspace_ssh_host_port,
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


def test_service_tunnel_ports_are_inferred_from_loopback_tcp_publications(config: Config) -> None:
    data = config.model_dump()
    data["services"]["support"]["container"] = {
        "network_mode": "bridge",
        "ports": [
            {"target": 3210, "published": 3210, "host_ip": "127.0.0.1"},
            {"target": 5353, "published": 5353, "host_ip": "127.0.0.1", "protocol": "udp"},
            {"target": 8003, "published": 8003, "host_ip": "10.88.0.1"},
        ],
    }

    parsed = Config.model_validate(data)

    assert parsed.service_tunnel_ports("support", "home") == [3210]


def test_git_source_args_default_empty_and_accept_clone_options(config: Config) -> None:
    assert config.workspace_spec("codespace", "home", "default").source.args == []
    data = config.model_dump()
    data["projects"]["codespace"]["source"]["args"] = ["--depth=1", "--single-branch"]

    parsed = Config.model_validate(data)

    assert parsed.workspace_spec("codespace", "home", "default").source.args == [
        "--depth=1",
        "--single-branch",
    ]


@pytest.mark.parametrize("args", [[""], [" "], [1], "--depth=1"])
def test_git_source_args_reject_invalid_values(config: Config, args: object) -> None:
    data = config.model_dump()
    data["projects"]["codespace"]["source"]["args"] = args

    with pytest.raises(ValidationError):
        Config.model_validate(data)


def test_empty_source_rejects_git_args(config: Config) -> None:
    data = config.model_dump()
    data["projects"]["scratch"]["source"]["args"] = ["--depth=1"]

    with pytest.raises(ValidationError, match="Extra inputs"):
        Config.model_validate(data)


def test_example_config_loads() -> None:
    config = load_config(Path("config.example.yaml"))

    assert list(config.projects) == [
        "codespace",
        "learn-ml",
        "standalone-binaries",
        "notes",
        "scratch",
        "private-repo",
    ]
    assert config.projects["codespace"].source.args == []
    assert list(config.services) == ["support", "vllm", "sglang", "lobehub", "chatbox"]
    assert config.workspace_spec("codespace", "workstation", "default").id == (
        "space:codespace/default@workstation"
    )
    workspace = config.workspace_spec("codespace", "workstation", "default")
    assert workspace.container.is_bridge
    assert "ATUIN_SYNC_ADDRESS" not in workspace.container.environment
    assert [
        (secret.source, secret.uid, secret.gid, secret.mode)
        for secret in workspace.container.secrets
    ] == [
        ("huggingface_token", None, None, 0o400),
        ("atuin_db_uri", None, None, 0o400),
        ("github_action_token", "5230", "5230", 0o400),
    ]
    support = config.service_spec("support", "gpu-host").container
    assert support.is_bridge
    assert not support.ports
    assert not support.secrets
    assert not support.environment
    for service in ("vllm", "sglang"):
        spec = config.service_spec(service, "gpu-host")
        assert spec.container.is_bridge
        assert spec.container.ports
        assert all(port.host_ip == "10.88.0.1" for port in spec.container.ports)
        assert spec.container.environment["SERVE_HOST"] == "0.0.0.0"  # noqa: S104


def test_load_config_rejects_non_mapping(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("- invalid\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must be a mapping"):
        load_config(path)


def test_source_union_and_default_paths(config: Config) -> None:
    managed = config.workspace_spec("codespace", "home", "default")
    direct = config.workspace_spec("personal", "home", "default")
    empty = config.workspace_spec("scratch", "home", "default")

    assert managed.source.model_dump() == {
        "type": "github",
        "repository": "curoky/codespace",
        "args": [],
    }
    assert managed.source.clone_url == "git@github.com:curoky/codespace.git"
    assert managed.checkout_path == "/workspace/codespace"
    assert direct.source.model_dump() == {
        "type": "git",
        "url": "git@github.com:curoky/codespace.git",
        "args": [],
    }
    assert empty.source.type == "empty"
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


def test_project_layers_apply_host_defaults_and_merge_volumes_by_target(
    config: Config,
) -> None:
    data = config.model_dump()
    data["hosts"]["home"]["container"] = {
        "environment": {"HOST": "1"},
        "devices": ["/dev/fuse"],
        "pids_limit": 64,
        "volumes": ["/host/base:/data"],
    }
    data["projects"]["codespace"]["container"] = {
        "environment": {"PROJECT": "1"},
        "cap_add": ["NET_RAW"],
    }
    data["projects"]["codespace"]["hosts"]["home"]["container"] = {
        "environment": {"PLACEMENT": "1"},
        "pids_limit": 128,
        "volumes": ["/host/placement:/data:ro"],
    }
    data["projects"]["codespace"]["hosts"]["home"]["image"] = "workspace:placement"

    parsed = Config.model_validate(data)
    resolved = parsed.resolved_project_container("codespace", "home")

    assert resolved.environment == {
        "CODESPACE_ENCRYPTED_PATH": "/workspace.enc",
        "HOST": "1",
        "PROJECT": "1",
        "PLACEMENT": "1",
    }
    assert resolved.devices == ["/dev/fuse"]
    assert resolved.cap_add == ["NET_RAW"]
    assert resolved.pids_limit == 128
    volumes = {volume.target: volume for volume in resolved.volumes}
    assert volumes["/workspace"].source == "${RESOURCE_DATA}/workspace"
    assert volumes["/data"].source == "/host/placement"
    assert volumes["/data"].read_only is True
    assert "/host/base" not in {volume.source for volume in resolved.volumes}
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
    assert resolved.environment == {"BASE": "1", "PLACEMENT": "1"}
    assert resolved.devices == ["/dev/fuse"]
    assert resolved.pids_limit == 64


@pytest.mark.parametrize("kind", ["projects", "services"])
@pytest.mark.parametrize(
    ("override", "cleared"),
    [
        (None, False),
        ({}, False),
        ({"environment": None, "devices": None, "pids_limit": None}, False),
        ({"environment": {}, "devices": [], "pids_limit": 0}, True),
    ],
)
def test_container_overrides_distinguish_null_from_empty(
    config: Config, kind: str, override: object, cleared: bool
) -> None:
    data = config.model_dump()
    data["hosts"]["home"]["container"] = {
        "environment": {"HOST": "1"},
        "devices": ["/dev/fuse"],
        "pids_limit": 64,
    }
    resource = "scratch" if kind == "projects" else "support"
    data[kind][resource]["hosts"]["home"]["container"] = override
    configured = Config.model_validate(data)
    resolved = (
        configured.workspace_spec(resource, "home", "default").container
        if kind == "projects"
        else configured.service_spec(resource, "home").container
    )

    expected_environment = {"HOST": "1"}
    if kind == "projects":
        expected_environment["CODESPACE_ENCRYPTED_PATH"] = "/workspace.enc"
    assert resolved.environment == expected_environment
    assert resolved.devices == ([] if cleared else ["/dev/fuse"])
    assert resolved.pids_limit == (0 if cleared else 64)
    assert configured.model_dump() == Config.model_validate(configured.model_dump()).model_dump()


@pytest.mark.parametrize("kind", ["projects", "services"])
def test_resolved_containers_have_concrete_collections(config: Config, kind: str) -> None:
    data = config.model_dump()
    data["project_defaults"]["container"] = {
        "environment": data["project_defaults"]["container"]["environment"],
        "volumes": data["project_defaults"]["container"]["volumes"],
    }
    configured = Config.model_validate(data)
    before = configured.model_dump()
    resolved = (
        configured.workspace_spec("scratch", "home", "default").container
        if kind == "projects"
        else configured.service_spec("support", "home").container
    )

    assert resolved.cap_add == []
    assert resolved.security_opt == []
    assert resolved.network_mode == ("bridge" if kind == "projects" else "host")
    assert resolved.ulimits == {}
    assert resolved.environment == (
        {"CODESPACE_ENCRYPTED_PATH": "/workspace.enc"} if kind == "projects" else {}
    )
    assert resolved.secrets == []
    assert resolved.devices == []
    assert resolved.ports == []
    assert bool(resolved.volumes) is (kind == "projects")
    resolved.environment["LOCAL"] = "1"
    resolved.devices.append("/dev/fuse")
    assert configured.model_dump() == before


def test_empty_collections_clear_all_inherited_container_values(config: Config) -> None:
    data = config.model_dump()
    data["projects"]["scratch"]["container"] = {
        "environment": {"PROJECT": "1"},
        "devices": ["/dev/fuse"],
        "secrets": [{"source": "api_token"}],
        "ports": [{"target": 80, "published": 8080, "host_ip": "127.0.0.1"}],
    }
    empty: dict[str, object] = {
        "cap_add": [],
        "security_opt": [],
        "ulimits": {},
        "secrets": [],
        "devices": [],
        "ports": [],
    }
    data["projects"]["scratch"]["hosts"]["home"]["container"] = empty
    configured = Config.model_validate(data)

    resolved = configured.workspace_spec("scratch", "home", "default").container

    assert resolved.model_dump(include=set(empty)) == empty
    assert config.project_defaults.container.cap_add == ["NET_RAW", "SYS_ADMIN"]


def test_project_cannot_clear_required_volumes(config: Config) -> None:
    data = config.model_dump()
    data["projects"]["scratch"]["container"] = {"volumes": []}

    with pytest.raises(ValidationError, match="missing required targets"):
        Config.model_validate(data)


def test_service_requires_resolved_network_mode(config: Config) -> None:
    data = config.model_dump()
    data["services"]["support"]["container"] = {}

    with pytest.raises(ValidationError, match="network_mode"):
        Config.model_validate(data)


def test_invalid_container_layer_is_rejected_even_when_overridden(config: Config) -> None:
    data = config.model_dump()
    data["hosts"]["home"]["container"] = {"cap_add": ["NET_RAW", "NET_RAW"]}
    data["projects"]["scratch"]["container"] = {"cap_add": []}

    with pytest.raises(ValidationError, match="duplicate"):
        Config.model_validate(data)


def test_config_accepts_compose_volume_short_syntax(config: Config) -> None:
    data = config.model_dump()
    data["project_defaults"]["container"]["volumes"].append("/host/path:/opt/data:ro")

    parsed = Config.model_validate(data)

    assert parsed.project_defaults.container.volumes is not None
    assert parsed.project_defaults.container.volumes[-1].source == "/host/path"
    assert parsed.project_defaults.container.volumes[-1].read_only is True


@pytest.mark.parametrize(
    "source",
    [
        "${RESOURCE_DATA}/../outside",
        "${RESOURCE_DATA}/cache/../../outside",
        "${RESOURCE_DATA}/./cache",
        "${DATA}",
    ],
)
def test_resource_data_rejects_invalid_subpaths(config: Config, source: str) -> None:
    data = config.model_dump()
    data["project_defaults"]["container"]["volumes"][0]["source"] = source

    with pytest.raises(ValidationError):
        Config.model_validate(data)


@pytest.mark.parametrize("target", ["/workspace", "/upload", "/run/codespace-control"])
def test_workspace_volumes_require_image_runtime_targets(config: Config, target: str) -> None:
    data = config.model_dump()
    data["project_defaults"]["container"]["volumes"] = [
        volume
        for volume in data["project_defaults"]["container"]["volumes"]
        if volume["target"] != target
    ]

    with pytest.raises(ValidationError, match="missing required targets"):
        Config.model_validate(data)


def test_workspace_requires_encrypted_target_configuration(config: Config) -> None:
    data = config.model_dump()
    del data["project_defaults"]["container"]["environment"]["CODESPACE_ENCRYPTED_PATH"]

    with pytest.raises(ValidationError, match="CODESPACE_ENCRYPTED_PATH"):
        Config.model_validate(data)


def test_encrypted_workspace_target_is_resolved_from_environment(config: Config) -> None:
    data = config.model_dump()
    data["project_defaults"]["container"]["environment"]["CODESPACE_ENCRYPTED_PATH"] = "/ciphertext"
    data["projects"]["codespace"]["encrypted"] = True
    data["secrets"]["codespace_workspace_key"] = "test-key"

    spec = Config.model_validate(data).workspace_spec("codespace", "home", "default")
    resolved = spec.resolve_data_path("/home/x/codespace/workspaces/codespace/default")

    assert {volume.source: volume.target for volume in resolved.volumes}[
        "/home/x/codespace/workspaces/codespace/default/workspace"
    ] == "/ciphertext"
    assert set(spec.container.volumes[0].model_dump()) == {
        "type",
        "source",
        "target",
        "read_only",
    }


@pytest.mark.parametrize("target", ["relative", "/workspace/../ciphertext"])
def test_encrypted_workspace_target_must_be_absolute_and_normalized(
    config: Config, target: str
) -> None:
    data = config.model_dump()
    data["project_defaults"]["container"]["environment"]["CODESPACE_ENCRYPTED_PATH"] = target

    with pytest.raises(ValidationError, match="absolute normalized path"):
        Config.model_validate(data)


@pytest.mark.parametrize(
    ("target", "error"),
    [
        ("/upload", "volume targets must be unique"),
        ("/workspace/nested", "overlaps another volume"),
        ("/var/lib/codespace", "image-owned state"),
        ("/run/secrets/codespace_workspace_key", "image-owned state"),
        ("/home/x", "overlaps"),
    ],
)
def test_workspace_volumes_reject_conflicting_targets(
    config: Config, target: str, error: str
) -> None:
    data = config.model_dump()
    data["project_defaults"]["container"]["volumes"].append(
        {"type": "bind", "source": "${RESOURCE_DATA}/extra", "target": target}
    )

    with pytest.raises(ValidationError, match=error):
        Config.model_validate(data)


@pytest.mark.parametrize("target", ["/workspace", "/upload"])
def test_workspace_rejects_conflicting_encrypted_target(config: Config, target: str) -> None:
    data = config.model_dump()
    data["project_defaults"]["container"]["environment"]["CODESPACE_ENCRYPTED_PATH"] = target

    with pytest.raises(ValidationError, match=r"overlaps|leave /workspace"):
        Config.model_validate(data)


@pytest.mark.parametrize("field", ["volumes", "secrets"])
def test_container_options_cannot_shadow_configured_workspace_mounts(
    config: Config, field: str
) -> None:
    data = config.model_dump()
    data["projects"]["codespace"]["container"] = {
        field: (
            ["/host/upload:/upload"]
            if field == "volumes"
            else [{"source": "api_key", "target": "/upload/key"}]
        ),
    }

    with pytest.raises(ValidationError, match="overlaps"):
        Config.model_validate(data)


def test_service_accepts_resource_data_placeholder(config: Config) -> None:
    volumes = config.resolved_service_container("vllm", "office").volumes

    assert volumes[0].source == "${RESOURCE_DATA}"
    assert volumes[0].target == "/root/.cache/huggingface"


def test_service_resolves_data_without_mutating_config(config: Config) -> None:
    data = config.model_dump()
    data["services"]["vllm"]["container"]["volumes"] = [
        "${RESOURCE_DATA}:/data:ro",
        "/host/cache:/cache",
        {"type": "bind", "source": "${RESOURCE_DATA}/models", "target": "/models"},
    ]
    configured = Config.model_validate(data)
    spec = configured.service_spec("vllm", "office")

    resolved = spec.resolve_data_path("/home/x/codespace/services/vllm")

    assert [volume.mount() for volume in resolved.volumes] == [
        {
            "type": "bind",
            "source": "/home/x/codespace/services/vllm",
            "target": "/data",
            "read_only": True,
        },
        {"type": "bind", "source": "/host/cache", "target": "/cache", "read_only": False},
        {
            "type": "bind",
            "source": "/home/x/codespace/services/vllm/models",
            "target": "/models",
            "read_only": False,
        },
    ]
    assert [volume.source for volume in spec.container.volumes] == [
        "${RESOURCE_DATA}",
        "/host/cache",
        "${RESOURCE_DATA}/models",
    ]


@pytest.mark.parametrize("kind, name", [("projects", "scratch"), ("services", "support")])
@pytest.mark.parametrize("source", ["relative", "${SERVICE_DATA}", "${OTHER_DATA}", "/${DATA}"])
def test_config_rejects_invalid_mount_sources(
    config: Config, kind: str, name: str, source: str
) -> None:
    data = config.model_dump()
    data[kind][name]["container"] = {
        **({"network_mode": "host"} if kind == "services" else {}),
        "volumes": [f"{source}:/data"],
    }

    with pytest.raises(ValidationError):
        Config.model_validate(data)


def test_ports_require_bridge_network(config: Config) -> None:
    data = config.model_dump()
    data["services"]["support"]["container"] = {
        "network_mode": "host",
        "ports": [
            {
                "target": 8080,
                "published": 3000,
                "host_ip": "127.0.0.1",
            }
        ],
    }

    with pytest.raises(ValidationError, match="only in bridge mode"):
        Config.model_validate(data)


@pytest.mark.parametrize("scope", ["defaults", "host", "project", "placement"])
def test_project_network_is_fixed_to_bridge(config: Config, scope: str) -> None:
    data = config.model_dump()
    match scope:
        case "defaults":
            data["project_defaults"]["container"]["network_mode"] = "host"
        case "host":
            data["hosts"]["home"]["container"] = {"network_mode": "host"}
        case "project":
            data["projects"]["codespace"]["container"] = {"network_mode": "host"}
        case "placement":
            data["projects"]["codespace"]["hosts"]["home"]["container"] = {"network_mode": "host"}
        case _:
            raise AssertionError(f"unknown scope: {scope}")

    with pytest.raises(ValidationError, match="bridge"):
        Config.model_validate(data)


@pytest.mark.parametrize(
    "target",
    [
        "/workspace/generated",
        "/workspace.enc",
        "/upload",
        "/run/codespace-control/agent.sock",
        "/var/lib/codespace",
        "/var/lib/codespace/provider-authorized",
    ],
)
def test_project_rejects_reserved_environment_and_mounts(config: Config, target: str) -> None:
    environment = config.model_dump()
    environment["projects"]["codespace"]["container"] = {
        "environment": {"CODESPACE_SOURCE_TYPE": "empty"}
    }
    with pytest.raises(ValidationError, match="reserved environment"):
        Config.model_validate(environment)

    git_args = config.model_dump()
    git_args["projects"]["codespace"]["container"] = {"environment": {"CODESPACE_GIT_ARGS": "[]"}}
    with pytest.raises(ValidationError, match="reserved environment"):
        Config.model_validate(git_args)

    volume = config.model_dump()
    volume["projects"]["codespace"]["container"] = {
        "volumes": [
            {
                "type": "bind",
                "source": "/host/data",
                "target": target,
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


def test_resource_data_placeholder_resolves_for_projects(config: Config) -> None:
    data = config.model_dump()
    data["projects"]["codespace"]["container"] = {"volumes": ["${RESOURCE_DATA}/models:/models"]}

    spec = Config.model_validate(data).workspace_spec("codespace", "home", "default")

    resolved = spec.resolve_data_path("/home/x/codespace/workspaces/codespace/default")
    volumes = {volume.target: volume for volume in resolved.volumes}
    assert volumes["/models"].source == ("/home/x/codespace/workspaces/codespace/default/models")


def test_unknown_host_reference_is_rejected(config: Config) -> None:
    data = config.model_dump()
    data["projects"]["codespace"]["hosts"] = {"missing": {}}

    with pytest.raises(ValidationError, match="unknown host"):
        Config.model_validate(data)


def test_host_cannot_use_workspace_ssh_prefix(config: Config) -> None:
    data = config.model_dump()
    data["hosts"]["space-home"] = {}

    with pytest.raises(ValidationError, match="reserved Workspace SSH prefix"):
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
    identity = Resource("home", "debug", "codespace").id
    spec = config.workspace_spec("codespace", "home", "debug")
    paths = HostDataPaths("/home/x/codespace")

    assert identity == "space:codespace/debug@home"
    assert spec.id == identity
    actual = spec.to_workspace("container-id", status="running")
    assert spec.container_name == actual.container_name == "space-codespace-debug"
    assert actual.ssh_alias == "space-codespace-debug-home"
    assert spec.ssh_host_port == actual.ssh_host_port == 28098
    assert workspace_ssh_host_port(spec.container_name) == actual.ssh_host_port
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
    assert paths.workspace("codespace", "debug") == ("/home/x/codespace/workspaces/codespace/debug")
    assert paths.service("support") == "/home/x/codespace/services/support"


def test_workspace_identity_has_unambiguous_component_boundaries() -> None:
    assert Resource("home", "c", "a-b").id != Resource("home", "b-c", "a").id


def test_workspace_names_follow_host_scope(config: Config) -> None:
    home = config.workspace_spec("codespace", "home", "debug").to_workspace(
        "home-container", status="running"
    )
    office = home.model_copy(update={"host": "office", "container_id": "office-container"})

    assert home.container_name == office.container_name == "space-codespace-debug"
    assert home.ssh_alias == "space-codespace-debug-home"
    assert office.ssh_alias == "space-codespace-debug-office"
    assert home.id != office.id
    assert home.ssh_host_port == office.ssh_host_port
