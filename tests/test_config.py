"""Tests for the final configuration, placement, and identity contracts."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from codespace.config import Config, load_config


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


@pytest.mark.parametrize("ports", [[0], [65536], [True], ["8005"]])
@pytest.mark.parametrize("scope", ["project_defaults", "project", "service"])
def test_tunnel_ports_reject_invalid_values(
    config: Config, ports: list[object], scope: str
) -> None:
    data = config.model_dump()
    targets = {
        "project_defaults": data["project_defaults"],
        "project": data["projects"]["codespace"],
        "service": data["services"]["support"],
    }
    target = targets[scope]
    target["tunnel_ports"] = ports
    with pytest.raises(ValidationError):
        Config.model_validate(data)


def test_service_tunnel_ports_are_explicit_container_ports(config: Config) -> None:
    data = config.model_dump()
    data["services"]["support"]["tunnel_ports"] = [8080, 8008]
    data["services"]["support"]["container"]["ports"] = [
        {"target": 8080, "published": 8110, "host_ip": "127.0.0.1"},
        {"target": 8081, "published": 8111, "host_ip": "127.0.0.1"},
        {
            "target": 5353,
            "published": 5353,
            "host_ip": "127.0.0.1",
            "protocol": "udp",
        },
    ]

    parsed = Config.model_validate(data)

    assert parsed.service_tunnel_ports("support") == [8080, 8008]
    assert parsed.service_port_publication("support", "home", 8080) == ("127.0.0.1", 8110)
    assert parsed.service_port_publication("support", "home", 8008) is None


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

    assert config.project_defaults.resource_image == "ghcr.io/curoky/codespace:workspace-resource"
    for project_id, project in config.projects.items():
        for host in project.hosts:
            config.workspace_spec(project_id, host, "default")
    for service_id, service in config.services.items():
        for host in service.hosts:
            config.service_spec(service_id, host)


def test_example_internal_only_service_has_no_host_publication() -> None:
    config = load_config(Path("config.example.yaml"))

    for host in config.services["secret"].hosts:
        assert config.resolved_service_container("secret", host).ports == []


@pytest.mark.parametrize(
    ("service", "home"),
    [("vllm", "/home/x"), ("sglang", "/root")],
)
def test_example_gpu_service_sets_huggingface_environment_at_startup(
    service: str, home: str
) -> None:
    config = load_config(Path("config.example.yaml"))
    script_path = Path(f"platform/container/services/{service}/rootfs/opt/{service}/serve.sh")
    script = script_path.read_text()

    for host in config.services[service].hosts:
        assert config.resolved_service_container(service, host).environment == {}
    assert f"export HF_HOME={home}/.cache/huggingface" in script
    assert "export HF_TOKEN_PATH=/run/secrets/huggingface_token" in script


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


@pytest.mark.parametrize("unknown", [{"unexpected": {}}, {"extra": "value"}])
def test_config_rejects_unknown_top_level_fields(
    config: Config,
    unknown: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        Config.model_validate({**config.model_dump(), **unknown})


def test_project_layers_apply_host_defaults_and_merge_volumes_by_source_or_target(
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
        "privileged": True,
        "volumes": ["${RESOURCE_DATA}/workspace:/workspace.enc"],
    }
    data["projects"]["codespace"]["container"]["pids_limit"] = 128
    data["projects"]["codespace"]["container"]["volumes"].append("/host/project:/data:ro")
    data["projects"]["codespace"]["container"]["image"] = "workspace:project"

    parsed = Config.model_validate(data)
    resolved = parsed.resolved_project_container("codespace", "home")

    assert resolved.environment == {
        "HOST": "1",
        "PROJECT": "1",
    }
    assert resolved.devices == ["/dev/fuse"]
    assert resolved.cap_add == ["NET_RAW"]
    assert resolved.privileged is True
    assert resolved.pids_limit == 128
    volumes = {volume.target: volume for volume in resolved.volumes}
    assert volumes["/data"].source == "/host/project"
    assert volumes["/data"].read_only is True
    assert "/host/base" not in {volume.source for volume in resolved.volumes}
    assert volumes["/workspace.enc"].source == "${RESOURCE_DATA}/workspace"
    assert "/workspace" not in volumes
    assert resolved.image == "workspace:project"


def test_workspace_uses_host_platform(config: Config) -> None:
    data = config.model_dump()
    data["hosts"]["home"]["container"] = {"platform": "linux/amd64"}

    parsed = Config.model_validate(data)

    assert parsed.workspace_spec("codespace", "home", "default").platform == "linux/amd64"


def test_service_layers_apply_host_defaults_before_service(config: Config) -> None:
    data = config.model_dump()
    data["hosts"]["home"]["container"] = {
        "devices": ["/dev/fuse"],
        "pids_limit": 64,
    }
    data["services"]["support"]["container"]["image"] = "support:pinned"
    data["services"]["support"]["container"]["environment"] = {"SERVICE": "1"}

    parsed = Config.model_validate(data)
    resolved = parsed.resolved_service_container("support", "home")

    assert parsed.service_spec("support", "home").image == "support:pinned"
    assert resolved.restart == "unless-stopped"
    assert resolved.environment == {"SERVICE": "1"}
    assert resolved.devices == ["/dev/fuse"]
    assert resolved.pids_limit == 64


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
    config: Config, override: object, cleared: bool
) -> None:
    data = config.model_dump()
    data["hosts"]["home"]["container"] = {
        "environment": {"HOST": "1"},
        "devices": ["/dev/fuse"],
        "pids_limit": 64,
    }
    data["projects"]["scratch"]["container"] = override
    configured = Config.model_validate(data)
    resolved = configured.workspace_spec("scratch", "home", "default").container

    expected_environment = {"HOST": "1"}
    assert resolved.environment == expected_environment
    assert resolved.devices == ([] if cleared else ["/dev/fuse"])
    assert resolved.pids_limit == (0 if cleared else 64)
    assert configured.model_dump() == Config.model_validate(configured.model_dump()).model_dump()


def test_empty_collections_clear_all_inherited_container_values(config: Config) -> None:
    data = config.model_dump()
    data["hosts"]["home"]["container"] = {
        "cap_add": ["NET_RAW"],
        "security_opt": ["disable"],
        "ulimits": {"memlock": {"soft": -1, "hard": -1}},
        "devices": ["/dev/fuse"],
        "secrets": [{"source": "api_token"}],
    }
    empty: dict[str, object] = {
        "cap_add": [],
        "security_opt": [],
        "ulimits": {},
        "secrets": [],
        "devices": [],
    }
    data["projects"]["scratch"]["container"] = empty
    configured = Config.model_validate(data)

    resolved = configured.workspace_spec("scratch", "home", "default").container

    assert resolved.model_dump(include=set(empty)) == empty
    assert config.project_defaults.container.cap_add == ["NET_RAW", "SYS_ADMIN"]


def test_project_can_clear_all_configured_volumes(config: Config) -> None:
    data = config.model_dump()
    data["projects"]["scratch"]["container"] = {"volumes": []}

    spec = Config.model_validate(data).workspace_spec("scratch", "home", "default")
    resolved = spec.container.resolve_data_path("/home/x/codespace/workspaces/scratch/default")

    assert resolved.volumes == []


def test_encrypted_workspace_uses_configured_ciphertext_target(config: Config) -> None:
    data = config.model_dump()
    data["projects"]["codespace"]["encrypted"] = True
    data["projects"]["codespace"]["container"] = {
        "volumes": ["${RESOURCE_DATA}/workspace:/workspace.enc"],
        "secrets": [
            {"source": "codespace_workspace_key", "uid": "5230", "gid": "5230", "mode": 0o400}
        ],
    }
    data["secrets"]["codespace_workspace_key"] = "test-key"

    spec = Config.model_validate(data).workspace_spec("codespace", "home", "default")
    resolved = spec.container.resolve_data_path("/home/x/codespace/workspaces/codespace/default")

    assert {volume.source: volume.target for volume in resolved.volumes}[
        "/home/x/codespace/workspaces/codespace/default/workspace"
    ] == "/workspace.enc"


def test_service_resolves_data_without_mutating_config(config: Config) -> None:
    data = config.model_dump()
    data["services"]["vllm"]["container"]["volumes"] = [
        "${RESOURCE_DATA}:/data:ro",
        "/host/cache:/cache",
        {"type": "bind", "source": "${RESOURCE_DATA}/models", "target": "/models"},
    ]
    configured = Config.model_validate(data)
    spec = configured.service_spec("vllm", "office")

    resolved = spec.container.resolve_data_path("/home/x/codespace/services/vllm")

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

    resolved = spec.container.resolve_data_path("/home/x/codespace/workspaces/codespace/default")
    volumes = {volume.target: volume for volume in resolved.volumes}
    assert volumes["/models"].source == ("/home/x/codespace/workspaces/codespace/default/models")


def test_unknown_host_reference_is_rejected(config: Config) -> None:
    data = config.model_dump()
    data["projects"]["codespace"]["hosts"] = ["missing"]

    with pytest.raises(ValidationError, match="unknown host"):
        Config.model_validate(data)


def test_encrypted_project_requires_syncable_key(config: Config) -> None:
    data = config.model_dump()
    data["projects"]["codespace"]["encrypted"] = True

    with pytest.raises(ValidationError, match="codespace_workspace_key"):
        Config.model_validate(data)

    data["secrets"]["codespace_workspace_key"] = "test-key"
    data["projects"]["codespace"]["container"] = {
        "secrets": [{"source": "codespace_workspace_key"}]
    }
    assert (
        Config.model_validate(data).workspace_spec("codespace", "home", "default").encrypted is True
    )


def test_project_inherits_default_encryption(config: Config) -> None:
    data = config.model_dump()
    data["project_defaults"]["encrypted"] = True
    data["project_defaults"]["container"]["secrets"] = [{"source": "codespace_workspace_key"}]
    data["secrets"]["codespace_workspace_key"] = "test-key"

    inherited = Config.model_validate(data)
    assert inherited.workspace_spec("codespace", "home", "default").encrypted is True

    data["projects"]["codespace"]["encrypted"] = False
    overridden = Config.model_validate(data)
    assert overridden.workspace_spec("codespace", "home", "default").encrypted is False


def test_tokens_are_seeded_without_leaking_from_repr(config: Config) -> None:
    data = config.model_dump()
    data["tokens"] = {"github": "ghp_example"}

    parsed = Config.model_validate(data)

    assert parsed.seed_tokens() == {"github": "ghp_example"}
    assert "ghp_example" not in repr(parsed)
