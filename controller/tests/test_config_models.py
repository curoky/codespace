"""Tests for strict YAML configuration and deterministic resource identity."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from controller.config import Config, load_config
from controller.models import (
    CreateInstanceRequest,
    HostDataPaths,
    environment_id,
    ssh_port,
)

# Minimal valid development container block reused by success-path inline configs.
_CONTAINER: dict[str, object] = {
    "network_mode": "host",
    "cap_add": ["NET_RAW", "SYS_ADMIN"],
    "security_opt": ["disable", "seccomp=unconfined"],
    "pids_limit": -1,
    "ulimits": {"memlock": {"soft": -1, "hard": -1}},
}

# A host declared with no options: network_mode now lives in the container block,
# so a plain SSH host needs nothing of its own.
_SSH_HOST: dict[str, object] = {}

# Same block rendered as YAML for the file-based tests.
_CONTAINER_YAML = """
    container:
      network_mode: host
      cap_add: [NET_RAW, SYS_ADMIN]
      security_opt: [disable, seccomp=unconfined]
      pids_limit: -1
      ulimits:
        memlock: {soft: -1, hard: -1}
"""


def _config(
    *,
    container: dict[str, object] | None = None,
    hosts: dict[str, object] | None = None,
    items: dict[str, object] | None = None,
    **overrides: object,
) -> dict[str, object]:
    """Build a valid config dict around the ``workspaces`` catalog for inline tests."""
    data: dict[str, object] = {
        "workspaces": {
            "defaults": {
                "image": "img",
                "container": container if container is not None else _CONTAINER,
            },
            "items": items
            if items is not None
            else {
                "devspace": {
                    "host": [{"name": "home"}],
                    "provider": "github",
                    "repo": "owner/repo",
                }
            },
        },
        "hosts": hosts if hosts is not None else {"home": _SSH_HOST},
    }
    data.update(overrides)
    return data


def test_load_config_reads_yaml_and_resolves_image(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        f"""
workspaces:
  defaults:
    image: "default:latest"
{_CONTAINER_YAML}
  items:
    devspace:
      host:
        - name: home
      repo: "github:curoky/devspace"
    service-api:
      host:
        - name: office
          platform: "linux/arm64"
      repo: "gitlab:group/service-api"
      image: "custom:latest"
hosts:
  home:
  office:
""",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.workspace_image("devspace") == "default:latest"
    assert config.workspace_image("service-api") == "custom:latest"
    assert config.workspaces.items["devspace"].provider == "github"
    assert config.workspaces.items["devspace"].repo == "curoky/devspace"
    assert config.workspaces.items["service-api"].provider == "gitlab"
    assert config.workspaces.items["devspace"].host_platform("home") is None
    assert config.workspaces.items["service-api"].host_platform("office") == "linux/arm64"


def test_config_rejects_invalid_workspace_platform(config: Config) -> None:
    data = config.model_dump()
    data["workspaces"]["items"]["devspace"]["host"][0]["platform"] = "linux/riscv64"

    with pytest.raises(ValidationError, match=r"linux/amd64.*linux/arm64"):
        Config.model_validate(data)


def test_config_rejects_workspace_without_resolved_network_mode() -> None:
    with pytest.raises(ValidationError, match=r"no resolved container\.network_mode"):
        Config.model_validate(
            _config(
                container={"cap_add": ["NET_RAW"]},
                hosts={"home": None},
            )
        )


def test_config_rejects_invalid_network_mode() -> None:
    with pytest.raises(ValidationError, match="network_mode must be"):
        Config.model_validate(_config(container={"network_mode": "none"}))


def test_config_rejects_shm_size_with_host_ipc() -> None:
    with pytest.raises(ValidationError, match=r"shm_size cannot be set.*ipc is 'host'"):
        Config.model_validate(
            _config(container={"network_mode": "host", "ipc": "host", "shm_size": "32g"})
        )


def test_config_rejects_combined_repo_with_separate_provider() -> None:
    with pytest.raises(ValidationError, match="either combined 'repo' or separate 'provider'"):
        Config.model_validate(
            _config(
                items={
                    "devspace": {
                        "host": [{"name": "home"}],
                        "provider": "github",
                        "repo": "github:curoky/devspace",
                    }
                }
            )
        )


def test_config_accepts_blank_workspace_and_open_path() -> None:
    config = Config.model_validate(
        _config(
            items={
                "scratch": {
                    "host": [{"name": "home"}],
                    "type": "blank",
                },
                "notes": {
                    "host": [{"name": "home"}],
                    "type": "blank",
                    "open_path": "/workspace/notes",
                },
            }
        )
    )

    scratch = config.workspaces.items["scratch"]
    assert scratch.type == "blank"
    assert scratch.repo is None
    assert scratch.provider is None
    assert scratch.resolved_open_path() == "/workspace"
    assert config.workspaces.items["notes"].resolved_open_path() == "/workspace/notes"


def test_config_accepts_git_workspace_from_combined_repo() -> None:
    config = Config.model_validate(
        _config(items={"abbie": {"host": [{"name": "home"}], "repo": "git:git@curoky:devspace"}})
    )

    abbie = config.workspaces.items["abbie"]
    assert abbie.type == "git"
    assert abbie.git_url == "git@curoky:devspace"
    assert abbie.repo is None
    assert abbie.provider is None
    assert abbie.resolved_open_path() == "/workspace/devspace"


def test_config_clone_path_overrides_target_and_open_path() -> None:
    config = Config.model_validate(
        _config(
            items={
                "playbook": {
                    "host": [{"name": "home"}],
                    "repo": "github:curoky/agent-playbook",
                    "clone_path": "/workspace/space/agent-playbook",
                    "open_path": "/workspace/space",
                },
                "defaulted": {
                    "host": [{"name": "home"}],
                    "repo": "github:curoky/agent-playbook",
                    "clone_path": "/workspace/space/agent-playbook",
                },
            }
        )
    )

    playbook = config.workspaces.items["playbook"]
    assert playbook.resolved_clone_path() == "/workspace/space/agent-playbook"
    assert playbook.resolved_open_path() == "/workspace/space"
    assert config.workspace_clone_path("playbook") == "/workspace/space/agent-playbook"

    # Without an explicit open_path, it falls back to the checkout directory.
    assert (
        config.workspaces.items["defaulted"].resolved_open_path()
        == "/workspace/space/agent-playbook"
    )


def test_config_clone_path_defaults_to_repo_target() -> None:
    config = Config.model_validate(
        _config(items={"devspace": {"host": [{"name": "home"}], "repo": "github:curoky/devspace"}})
    )

    assert config.workspaces.items["devspace"].resolved_clone_path() == "/workspace/devspace"


def test_config_rejects_clone_path_outside_workspace() -> None:
    with pytest.raises(ValidationError, match="path must be a directory under /workspace"):
        Config.model_validate(
            _config(
                items={
                    "devspace": {
                        "host": [{"name": "home"}],
                        "repo": "github:curoky/devspace",
                        "clone_path": "/etc/devspace",
                    }
                }
            )
        )


def test_config_rejects_relative_clone_path() -> None:
    with pytest.raises(ValidationError, match="path must be a directory under /workspace"):
        Config.model_validate(
            _config(
                items={
                    "devspace": {
                        "host": [{"name": "home"}],
                        "repo": "github:curoky/devspace",
                        "clone_path": "space/agent-playbook",
                    }
                }
            )
        )


def test_config_rejects_clone_path_equal_to_workspace_mount() -> None:
    with pytest.raises(ValidationError, match="path must be a directory under /workspace"):
        Config.model_validate(
            _config(
                items={
                    "devspace": {
                        "host": [{"name": "home"}],
                        "repo": "github:curoky/devspace",
                        "clone_path": "/workspace",
                    }
                }
            )
        )


def test_config_rejects_clone_path_with_parent_segments() -> None:
    with pytest.raises(ValidationError, match=r"path must not contain '\.\.' segments"):
        Config.model_validate(
            _config(
                items={
                    "devspace": {
                        "host": [{"name": "home"}],
                        "repo": "github:curoky/devspace",
                        "clone_path": "/workspace/../etc/devspace",
                    }
                }
            )
        )


def test_config_rejects_clone_path_on_blank_workspace() -> None:
    with pytest.raises(ValidationError, match=r"blank\.clone_path\s+Input should be None"):
        Config.model_validate(
            _config(
                items={
                    "scratch": {
                        "host": [{"name": "home"}],
                        "type": "blank",
                        "clone_path": "/workspace/scratch",
                    }
                }
            )
        )


def test_config_rejects_git_workspace_with_provider() -> None:
    with pytest.raises(ValidationError, match=r"git\.provider\s+Input should be None"):
        Config.model_validate(
            _config(
                items={
                    "abbie": {
                        "host": [{"name": "home"}],
                        "type": "git",
                        "git_url": "git@curoky:devspace",
                        "provider": "github",
                    }
                }
            )
        )


def test_config_rejects_git_workspace_without_git_url() -> None:
    with pytest.raises(ValidationError, match=r"git\.git_url\s+Field required"):
        Config.model_validate(_config(items={"abbie": {"host": [{"name": "home"}], "type": "git"}}))


def test_config_rejects_blank_workspace_with_repo() -> None:
    with pytest.raises(ValidationError, match=r"blank\.repo\s+Input should be None"):
        Config.model_validate(
            _config(
                items={
                    "scratch": {
                        "host": [{"name": "home"}],
                        "type": "blank",
                        "repo": "github:curoky/devspace",
                    }
                }
            )
        )


def test_config_rejects_repo_workspace_without_repo() -> None:
    with pytest.raises(ValidationError, match=r"repo\.repo\s+Field required"):
        Config.model_validate(
            _config(items={"devspace": {"host": [{"name": "home"}], "type": "repo"}})
        )


def test_config_rejects_relative_open_path() -> None:
    with pytest.raises(ValidationError, match="open_path must be an absolute path"):
        Config.model_validate(
            _config(
                items={
                    "scratch": {
                        "host": [{"name": "home"}],
                        "type": "blank",
                        "open_path": "relative/path",
                    }
                }
            )
        )


def test_config_resolves_per_host_podman_socket() -> None:
    config = Config.model_validate(
        _config(
            hosts={
                "home": _SSH_HOST,
                "office": {"podman_socket": "/tmp/podmanxd.sock"},
            }
        )
    )

    assert config.host_config("office").podman_socket == "/tmp/podmanxd.sock"
    assert config.host_config("home").podman_socket is None
    assert config.host_config("office").endpoint().podman_socket == "/tmp/podmanxd.sock"


def test_config_accepts_inherited_environment_for_ssh_host() -> None:
    config = Config.model_validate(
        _config(hosts={"home": {"environment": ["HTTP_PROXY", "_INTERNAL_TOKEN"]}})
    )

    assert config.host_config("home").environment == ["HTTP_PROXY", "_INTERNAL_TOKEN"]


@pytest.mark.parametrize("name", ["", "1INVALID", "INVALID-NAME", "INVALID.NAME"])
def test_config_rejects_invalid_inherited_environment_name(name: str) -> None:
    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        Config.model_validate(_config(hosts={"home": {"environment": [name]}}))


def test_config_rejects_duplicate_or_reserved_inherited_environment() -> None:
    with pytest.raises(ValidationError, match="must not contain duplicates"):
        Config.model_validate(
            _config(hosts={"home": {"environment": ["HTTP_PROXY", "HTTP_PROXY"]}})
        )
    with pytest.raises(ValidationError, match="must not inherit control-plane keys"):
        Config.model_validate(_config(hosts={"home": {"environment": ["SSHD_PORT"]}}))


def test_config_rejects_collision_between_inherited_and_explicit_environment() -> None:
    with pytest.raises(ValidationError, match="inherited host environment variables"):
        Config.model_validate(
            _config(
                container={
                    **_CONTAINER,
                    "environment": {"HTTP_PROXY": "http://configured:3128"},
                },
                hosts={"home": {"environment": ["HTTP_PROXY"]}},
            )
        )


def test_config_ssh_host_uses_host_network() -> None:
    config = Config.model_validate(_config())

    assert config.resolved_container("devspace", "home").is_bridge is False
    assert config.resolved_container("devspace", "home").network_mode == "host"


def test_config_bridge_via_host_container_enables_port_publishing() -> None:
    """network_mode lives in the container block and can be set per host override."""
    config = Config.model_validate(
        _config(
            hosts={"home": {"container": {"network_mode": "bridge"}}},
            items={
                "devspace": {
                    "host": [{"name": "home"}],
                    "provider": "github",
                    "repo": "owner/repo",
                    "published_ports": ["8080"],
                }
            },
        )
    )

    assert config.resolved_container("devspace", "home").is_bridge is True
    assert config.workspace_ports("devspace") == [(8080, 8080)]


def _bridge_workspace_config(published_ports: list[str]) -> dict[str, object]:
    return _config(
        hosts={
            "local": {
                "container": {"network_mode": "bridge"},
            },
        },
        items={
            "devspace": {
                "host": [{"name": "local"}],
                "provider": "github",
                "repo": "owner/repo",
                "published_ports": published_ports,
            }
        },
    )


def test_config_parses_workspace_ports_on_bridge_host() -> None:
    config = Config.model_validate(_bridge_workspace_config(["8080", "3000:5000"]))

    assert config.workspace_ports("devspace") == [(8080, 8080), (3000, 5000)]


def test_config_rejects_ports_on_host_network_host() -> None:
    with pytest.raises(ValidationError, match="port publishing requires bridge mode"):
        Config.model_validate(
            _config(
                items={
                    "devspace": {
                        "host": [{"name": "home"}],
                        "provider": "github",
                        "repo": "owner/repo",
                        "published_ports": ["8080"],
                    }
                }
            )
        )


def test_config_rejects_malformed_port_mapping() -> None:
    with pytest.raises(ValidationError, match="not a port number"):
        Config.model_validate(_bridge_workspace_config(["http"]))


def test_config_rejects_out_of_range_port() -> None:
    with pytest.raises(ValidationError, match="between 1 and 65535"):
        Config.model_validate(_bridge_workspace_config(["70000"]))


def test_config_rejects_duplicate_published_host_port() -> None:
    with pytest.raises(ValidationError, match="duplicate published host port"):
        Config.model_validate(_bridge_workspace_config(["8080", "8080:9090"]))


def test_config_workspace_ports_defaults_empty() -> None:
    config = Config.model_validate(_config())

    assert config.workspace_ports("devspace") == []


def test_config_resolved_container_uses_defaults(config: Config) -> None:
    resolved = config.resolved_container("devspace", "home")

    assert resolved.cap_add == ["NET_RAW", "SYS_ADMIN"]
    assert resolved.security_opt == ["disable", "seccomp=unconfined"]
    assert resolved.pids_limit == -1
    assert resolved.ulimits is not None
    assert {name: (u.soft, u.hard) for name, u in resolved.ulimits.items()} == {"memlock": (-1, -1)}
    assert resolved.volumes is not None
    assert [(v.source, v.target, v.read_only) for v in resolved.volumes] == [
        ("/etc/krb5.conf", "/etc/krb5.conf", True)
    ]
    # environment is unset in the fixture, so it stays None (engine default)
    assert resolved.environment is None


def test_config_resolved_container_applies_host_and_workspace_overrides() -> None:
    config = Config.model_validate(
        _config(
            container={
                "network_mode": "host",
                "cap_add": ["NET_RAW"],
                "security_opt": ["disable"],
                "pids_limit": -1,
                "ulimits": {},
                "environment": {"BASE": "1"},
            },
            hosts={
                "home": {
                    "container": {
                        "cap_add": ["NET_RAW", "SYS_ADMIN"],
                        "pids_limit": 100,
                    },
                }
            },
            items={
                "devspace": {
                    "host": [{"name": "home"}],
                    "provider": "github",
                    "repo": "owner/repo",
                    "container": {
                        "pids_limit": 200,
                        "environment": {"WORKSPACE": "1"},
                    },
                }
            },
        )
    )

    resolved = config.resolved_container("devspace", "home")

    # host override replaces cap_add wholesale; workspace override wins on pids_limit
    assert resolved.cap_add == ["NET_RAW", "SYS_ADMIN"]
    assert resolved.pids_limit == 200
    # environment is replaced wholesale by the workspace layer, not deep-merged
    assert resolved.environment == {"WORKSPACE": "1"}
    # security_opt untouched by any override, inherits default
    assert resolved.security_opt == ["disable"]


@pytest.mark.parametrize(
    "name",
    ["SSHD_PORT", "CODESPACE_OPEN_PATH", "CODESPACE_WORKSPACE_TYPE"],
)
def test_config_rejects_reserved_container_env_key(name: str) -> None:
    with pytest.raises(ValidationError, match="control-plane keys"):
        Config.model_validate(
            _config(
                container={
                    "network_mode": "host",
                    "cap_add": [],
                    "security_opt": [],
                    "pids_limit": -1,
                    "ulimits": {},
                    "environment": {name: "override"},
                }
            )
        )


def test_config_rejects_relative_container_volume_source() -> None:
    with pytest.raises(ValidationError, match="must be an absolute path"):
        Config.model_validate(
            _config(
                container={
                    "network_mode": "host",
                    "cap_add": [],
                    "security_opt": [],
                    "pids_limit": -1,
                    "ulimits": {},
                    "volumes": [{"source": "relative", "target": "/etc/x"}],
                }
            )
        )


@pytest.mark.parametrize(
    "target",
    [
        "/workspace",
        "/workspace/cache",
        "/workspace/../workspace",
        "/workspace.enc",
        "/upload",
        "/upload/incoming",
        "/cache",
        "/cache/build",
        "/run/codespace-control",
        "/run/codespace-control/agent.sock",
        "/home/x/.vscode-server",
        "/home/x/.trae",
        "/home/x/.trae-cn",
        "/home/x/.trae-server",
        "/home/x/.trae-cn-server",
        "/home/x/.trae/user_rules",
        "/home/x",
        "/",
    ],
)
def test_config_rejects_control_plane_mount_target_overlap(target: str) -> None:
    with pytest.raises(ValidationError, match="control-plane mount targets"):
        Config.model_validate(
            _config(
                container={
                    **_CONTAINER,
                    "volumes": [{"source": "/host/data", "target": target}],
                }
            )
        )


@pytest.mark.parametrize(
    "target",
    ["/workspace-old", "/uploads", "/run/codespace-control-old", "/etc/data"],
)
def test_config_allows_mount_targets_outside_control_plane_paths(target: str) -> None:
    config = Config.model_validate(
        _config(
            container={
                **_CONTAINER,
                "volumes": [{"source": "/host/data", "target": target}],
            }
        )
    )

    volumes = config.resolved_container("devspace", "home").volumes
    assert volumes is not None
    assert volumes[0].target == target


def _config_with_container(container: dict[str, object]) -> dict[str, object]:
    return _config(container={**_CONTAINER, **container})


def test_config_accepts_secrets_and_resolves_them() -> None:
    config = Config.model_validate(
        _config_with_container(
            {
                "secrets": [
                    "supabase_service_key",
                    {"source": "supabase_anon", "mode": "env", "target": "SUPABASE_ANON_KEY"},
                ],
            }
        )
    )

    resolved = config.resolved_container("devspace", "home")
    assert resolved.secrets is not None
    assert [(s.source, s.mode) for s in resolved.secrets] == [
        ("supabase_service_key", "mount"),
        ("supabase_anon", "env"),
    ]


def test_config_rejects_reserved_secret_env_target() -> None:
    with pytest.raises(ValidationError, match="must not use control-plane keys"):
        Config.model_validate(
            _config_with_container(
                {"secrets": [{"source": "x", "mode": "env", "target": "SSHD_PORT"}]}
            )
        )


def test_config_rejects_duplicate_secret_env_target() -> None:
    with pytest.raises(ValidationError, match="must not repeat names"):
        Config.model_validate(
            _config_with_container(
                {
                    "secrets": [
                        {"source": "a", "mode": "env", "target": "TOKEN"},
                        {"source": "b", "mode": "env", "target": "TOKEN"},
                    ]
                }
            )
        )


def test_config_rejects_secret_env_target_colliding_with_environment() -> None:
    with pytest.raises(ValidationError, match=r"collides with container\.environment"):
        Config.model_validate(
            _config_with_container(
                {
                    "environment": {"TOKEN": "static"},
                    "secrets": [{"source": "a", "mode": "env", "target": "TOKEN"}],
                }
            )
        )


@pytest.mark.parametrize("target", ["/workspace/secret", "/home/x/.trae/secret"])
def test_config_rejects_secret_mount_target_overlapping_control_plane(target: str) -> None:
    with pytest.raises(ValidationError, match="control-plane mount targets"):
        Config.model_validate(
            _config_with_container({"secrets": [{"source": "a", "target": target}]})
        )


def test_config_rejects_secret_env_target_colliding_with_inherited_host_env() -> None:
    with pytest.raises(ValidationError, match=r"as container\.secrets env target"):
        Config.model_validate(
            _config(
                container={
                    **_CONTAINER,
                    "secrets": [{"source": "a", "mode": "env", "target": "HTTP_PROXY"}],
                },
                hosts={"home": {"environment": ["HTTP_PROXY"]}},
            )
        )


def test_config_seeds_tokens_from_tokens_table(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        f"""
workspaces:
  defaults:
    image: "default:latest"
{_CONTAINER_YAML}
  items:
    devspace:
      host:
        - name: home
      repo: "github:curoky/devspace"
hosts:
  home:

tokens:
  github: "ghp_example"
""",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.seed_tokens() == {"github": "ghp_example"}
    assert "ghp_example" not in repr(config)


def test_config_seed_tokens_defaults_to_empty() -> None:
    config = Config.model_validate(_config())

    assert config.seed_tokens() == {}


@pytest.mark.parametrize("provider", ["github", "gitlab"])
def test_config_rejects_blank_token(provider: str) -> None:
    with pytest.raises(ValidationError, match="token must not be blank"):
        Config.model_validate(_config(tokens={provider: "   "}))


@pytest.mark.parametrize(
    ("host_options", "message"),
    [
        ({"podman_socket": "relative.sock"}, "absolute path"),
        ({"unknown": "x"}, "Extra inputs"),
    ],
)
def test_config_rejects_invalid_host_options(
    host_options: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        Config.model_validate(_config(hosts={"home": host_options}))


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (
            _config(
                hosts={},
                items={
                    "workspace": {
                        "host": [{"name": "home"}],
                        "provider": "github",
                        "repo": "owner/repo",
                    }
                },
            ),
            "at least one host",
        ),
        (
            _config(
                items={
                    "Bad": {
                        "host": [{"name": "home"}],
                        "provider": "github",
                        "repo": "owner/repo",
                    }
                }
            ),
            "workspace 'Bad'",
        ),
        (
            _config(
                items={
                    "workspace": {
                        "host": [{"name": "office"}],
                        "provider": "github",
                        "repo": "owner/repo",
                    }
                }
            ),
            "unknown host",
        ),
    ],
)
def test_config_rejects_invalid_cross_field_contract(
    data: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        Config.model_validate(data)


def test_config_rejects_unknown_fields(config: Config) -> None:
    data = config.model_dump()
    data["legacy_agents"] = {}

    with pytest.raises(ValidationError, match="Extra inputs"):
        Config.model_validate(data)


@pytest.mark.parametrize("missing", ["workspaces", "hosts"])
def test_config_requires_top_level_fields(config: Config, missing: str) -> None:
    data = config.model_dump()
    data.pop(missing)

    with pytest.raises(ValidationError, match="Field required"):
        Config.model_validate(data)


@pytest.mark.parametrize("instance", ["debug", "a1", "a-b", "x" * 32])
def test_create_request_accepts_valid_instance(instance: str) -> None:
    assert CreateInstanceRequest(host="home", instance=instance).instance == instance


@pytest.mark.parametrize("instance", ["Debug", "-bad", "bad_name", "x" * 33, ""])
def test_create_request_rejects_invalid_instance(instance: str) -> None:
    with pytest.raises(ValidationError):
        CreateInstanceRequest(host="home", instance=instance)


def test_resource_identity_contract_is_deterministic(config: Config) -> None:
    identity = environment_id("home", "devspace", "debug")
    spec = config.environment_spec("devspace", "home", "debug")

    assert identity == "codespace-home-devspace-debug"
    assert spec.identity == identity
    data_paths = HostDataPaths(root="/home/x/codespace")
    instance_paths = data_paths.instance("devspace", "debug")
    assert instance_paths.root == "/home/x/codespace/workspaces/devspace/debug"
    assert instance_paths.control == "/home/x/codespace/workspaces/devspace/debug/control"
    assert data_paths.deployment("sidecar") == "/home/x/codespace/deployments/sidecar"
    assert ssh_port(identity) == ssh_port(identity)
    assert 20_000 <= ssh_port(identity) <= 29_999


# --- Two-file layering (base + private extend) -------------------------------


def _write_base(tmp_path: Path) -> Path:
    base = tmp_path / "base.yaml"
    base.write_text(
        """
workspaces:
  defaults:
    image: "base:latest"
    container:
      network_mode: host
      cap_add: [NET_RAW]
deployments:
  sidecar:
    image: "ghcr.io/x/sidecar:latest"
    published_ports: ["8002:8002"]
    container:
      network_mode: host
      volumes: ["/run/podman/podman.sock:/run/podman/podman.sock"]
""",
        encoding="utf-8",
    )
    return base


def test_load_config_merges_extend_layer_onto_base(tmp_path: Path) -> None:
    _write_base(tmp_path)
    entry = tmp_path / "config.yaml"
    entry.write_text(
        """
extends: base.yaml
hosts:
  server:
    deployments: [sidecar]
workspaces:
  items:
    devspace:
      host: [{name: server}]
      repo: "github:curoky/devspace"
""",
        encoding="utf-8",
    )

    config = load_config(entry)

    # base scalar + block survive; extend adds hosts and workspace items by sub-key union.
    assert config.workspaces.defaults.image == "base:latest"
    assert config.workspaces.defaults.container.network_mode == "host"
    assert "sidecar" in config.deployments
    assert config.deployment_hosts("sidecar") == ["server"]
    assert config.workspaces.items["devspace"].provider == "github"


def test_load_config_extend_overrides_base_scalar_and_subkeys(tmp_path: Path) -> None:
    _write_base(tmp_path)
    entry = tmp_path / "config.yaml"
    entry.write_text(
        """
extends: base.yaml
workspaces:
  defaults:
    image: "override:latest"
  items:
    devspace:
      host: [{name: server}]
      repo: "github:curoky/devspace"
deployments:
  sidecar:
    image: "ghcr.io/x/sidecar:pinned"
hosts:
  server:
    deployments: [sidecar]
""",
        encoding="utf-8",
    )

    config = load_config(entry)

    assert config.workspaces.defaults.image == "override:latest"
    # Deployment block deep-merges: image is overridden, base published_ports kept.
    assert config.deployments["sidecar"].image == "ghcr.io/x/sidecar:pinned"
    assert config.deployments["sidecar"].published_ports == ["8002:8002"]


def test_load_config_rejects_extends_cycle(tmp_path: Path) -> None:
    a = tmp_path / "a.yaml"
    b = tmp_path / "b.yaml"
    a.write_text("extends: b.yaml\n", encoding="utf-8")
    b.write_text("extends: a.yaml\n", encoding="utf-8")

    with pytest.raises(ValueError, match="cycle"):
        load_config(a)


# --- Deployment schema and placement ----------------------------------------


def _deployment_config(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = _config(
        container={"network_mode": "host"},
        hosts={"server": {"deployments": ["sidecar"]}},
        items={"devspace": {"host": [{"name": "server"}], "provider": "github", "repo": "o/r"}},
        deployments={"sidecar": {"image": "sidecar:latest", "container": {"network_mode": "host"}}},
    )
    data.update(overrides)
    return data


def test_deployment_resolves_network_from_deployment_container() -> None:
    config = Config.model_validate(_deployment_config())

    resolved = config.resolved_deployment_container("sidecar", "server")
    assert resolved.network_mode == "host"
    assert config.deployment_hosts("sidecar") == ["server"]


def test_deployment_rejects_description() -> None:
    with pytest.raises(ValidationError, match="description"):
        Config.model_validate(
            _deployment_config(
                deployments={
                    "sidecar": {
                        "image": "sidecar:latest",
                        "description": "shared services",
                        "container": {"network_mode": "host"},
                    }
                }
            )
        )


def test_deployment_does_not_inherit_workspace_defaults() -> None:
    """A deployment starts from an empty container block, not workspaces.defaults."""
    config = Config.model_validate(_deployment_config())

    resolved = config.resolved_deployment_container("sidecar", "server")
    # workspaces.defaults grants NET_RAW/SYS_ADMIN; the deployment must not inherit them.
    assert resolved.cap_add is None


def test_deployment_host_bridge_override_wins() -> None:
    config = Config.model_validate(
        _deployment_config(
            hosts={
                "mac": {
                    "container": {"network_mode": "bridge"},
                    "deployments": ["sidecar"],
                }
            },
            workspaces={
                "defaults": {"image": "img", "container": {"network_mode": "host"}},
                "items": {
                    "devspace": {"host": [{"name": "mac"}], "provider": "github", "repo": "o/r"}
                },
            },
            deployments={"sidecar": {"image": "sidecar:latest"}},
        )
    )

    resolved = config.resolved_deployment_container("sidecar", "mac")
    assert resolved.is_bridge


def test_deployment_rejects_host_shm_size_with_host_ipc_override() -> None:
    with pytest.raises(ValidationError, match=r"shm_size cannot be set.*ipc is 'host'"):
        Config.model_validate(
            _deployment_config(
                hosts={
                    "server": {
                        "deployments": ["sidecar"],
                        "container": {"network_mode": "host", "shm_size": "32g"},
                    }
                },
                deployments={
                    "sidecar": {
                        "image": "sidecar:latest",
                        "container": {"ipc": "host"},
                    }
                },
            )
        )


def test_deployment_accepts_data_placeholder_volume() -> None:
    config = Config.model_validate(
        _deployment_config(
            deployments={
                "llm-vllm": {
                    "image": "llm:latest",
                    "container": {
                        "network_mode": "host",
                        "volumes": ["${DEPLOYMENT_DATA}:/root/.cache/huggingface"],
                    },
                }
            },
            hosts={"server": {"deployments": ["llm-vllm"]}},
        )
    )

    volume = config.deployments["llm-vllm"].container.volumes[0]
    assert volume.source == "${DEPLOYMENT_DATA}"
    assert volume.target == "/root/.cache/huggingface"


def test_config_rejects_host_referencing_unknown_deployment() -> None:
    with pytest.raises(ValidationError, match="unknown deployment"):
        Config.model_validate(_deployment_config(hosts={"server": {"deployments": ["ghost"]}}))


def test_config_rejects_deployment_without_resolved_network_mode() -> None:
    with pytest.raises(ValidationError, match=r"no resolved container\.network_mode"):
        Config.model_validate(
            _deployment_config(deployments={"sidecar": {"image": "sidecar:latest"}})
        )


def test_config_allows_no_deployments() -> None:
    config = Config.model_validate(_deployment_config(hosts={"server": {}}, deployments={}))
    assert config.deployments == {}
