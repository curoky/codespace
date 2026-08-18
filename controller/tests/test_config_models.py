"""Tests for strict YAML configuration and deterministic resource identity."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from controller.config import Config, load_config
from controller.models import (
    CreateInstanceRequest,
    environment_id,
    ssh_port,
)

# Minimal valid global container block reused by success-path inline configs.
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

# Same blocks rendered as YAML for the file-based tests.
_CONTAINER_YAML = """
container:
  network_mode: host
  cap_add: [NET_RAW, SYS_ADMIN]
  security_opt: [disable, seccomp=unconfined]
  pids_limit: -1
  ulimits:
    memlock: {soft: -1, hard: -1}
"""


def test_load_config_reads_yaml_and_resolves_image(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        f"""
default_image: "default:latest"
{_CONTAINER_YAML}
hosts:
  home:
  office:

projects:
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
""",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.project_image("devspace") == "default:latest"
    assert config.project_image("service-api") == "custom:latest"
    assert config.projects["devspace"].provider == "github"
    assert config.projects["devspace"].repo == "curoky/devspace"
    assert config.projects["service-api"].provider == "gitlab"
    assert config.projects["devspace"].host_platform("home") is None
    assert config.projects["service-api"].host_platform("office") == "linux/arm64"


def test_config_rejects_invalid_project_platform(config: Config) -> None:
    data = config.model_dump()
    data["projects"]["devspace"]["host"][0]["platform"] = "linux/riscv64"

    with pytest.raises(ValidationError, match=r"linux/amd64.*linux/arm64"):
        Config.model_validate(data)


def test_config_rejects_project_without_resolved_network_mode() -> None:
    with pytest.raises(ValidationError, match=r"no resolved container\.network_mode"):
        Config.model_validate(
            {
                "default_image": "img",
                "container": {"cap_add": ["NET_RAW"]},
                "hosts": {"home": None},
                "projects": {
                    "devspace": {
                        "host": [{"name": "home"}],
                        "provider": "github",
                        "repo": "owner/repo",
                    }
                },
            }
        )


def test_config_rejects_invalid_network_mode() -> None:
    with pytest.raises(ValidationError, match="network_mode must be"):
        Config.model_validate(
            {
                "default_image": "img",
                "container": {"network_mode": "none"},
                "hosts": {"home": _SSH_HOST},
                "projects": {
                    "devspace": {
                        "host": [{"name": "home"}],
                        "provider": "github",
                        "repo": "owner/repo",
                    }
                },
            }
        )


def test_config_rejects_combined_repo_with_separate_provider() -> None:
    with pytest.raises(ValidationError, match="either combined 'repo' or separate 'provider'"):
        Config.model_validate(
            {
                "default_image": "img",
                "container": _CONTAINER,
                "hosts": {"home": _SSH_HOST},
                "projects": {
                    "devspace": {
                        "host": [{"name": "home"}],
                        "provider": "github",
                        "repo": "github:curoky/devspace",
                    }
                },
            }
        )


def test_config_accepts_blank_project_and_open_path() -> None:
    config = Config.model_validate(
        {
            "default_image": "img",
            "container": _CONTAINER,
            "hosts": {"home": _SSH_HOST},
            "projects": {
                "scratch": {
                    "host": [{"name": "home"}],
                    "type": "blank",
                },
                "notes": {
                    "host": [{"name": "home"}],
                    "type": "blank",
                    "open_path": "/workspace/notes",
                },
            },
        }
    )

    scratch = config.projects["scratch"]
    assert scratch.type == "blank"
    assert scratch.repo is None
    assert scratch.provider is None
    assert scratch.resolved_open_path() == "/workspace"
    assert config.projects["notes"].resolved_open_path() == "/workspace/notes"


def test_config_rejects_blank_project_with_repo() -> None:
    with pytest.raises(ValidationError, match="blank project must not set"):
        Config.model_validate(
            {
                "default_image": "img",
                "container": _CONTAINER,
                "hosts": {"home": _SSH_HOST},
                "projects": {
                    "scratch": {
                        "host": [{"name": "home"}],
                        "type": "blank",
                        "repo": "github:curoky/devspace",
                    }
                },
            }
        )


def test_config_rejects_repo_project_without_repo() -> None:
    with pytest.raises(ValidationError, match="repo project requires"):
        Config.model_validate(
            {
                "default_image": "img",
                "container": _CONTAINER,
                "hosts": {"home": _SSH_HOST},
                "projects": {"devspace": {"host": [{"name": "home"}], "type": "repo"}},
            }
        )


def test_config_rejects_relative_open_path() -> None:
    with pytest.raises(ValidationError, match="open_path must be an absolute path"):
        Config.model_validate(
            {
                "default_image": "img",
                "container": _CONTAINER,
                "hosts": {"home": _SSH_HOST},
                "projects": {
                    "scratch": {
                        "host": [{"name": "home"}],
                        "type": "blank",
                        "open_path": "relative/path",
                    }
                },
            }
        )


def test_config_resolves_per_host_podman_socket() -> None:
    config = Config.model_validate(
        {
            "default_image": "img",
            "container": _CONTAINER,
            "hosts": {
                "home": _SSH_HOST,
                "office": {"podman_socket": "/tmp/podmanxd.sock"},
            },
            "projects": {
                "devspace": {
                    "host": [{"name": "home"}],
                    "provider": "github",
                    "repo": "owner/repo",
                }
            },
        }
    )

    assert config.host_config("office").resolved_podman_socket() == "/tmp/podmanxd.sock"
    assert config.host_config("home").resolved_podman_socket() == "/run/podman/podman.sock"
    assert config.host_config("home").type == "ssh"
    assert config.host_config("office").podman_socket == "/tmp/podmanxd.sock"


def test_config_accepts_explicit_podman_machine_host() -> None:
    config = Config.model_validate(
        {
            "default_image": "img",
            "container": _CONTAINER,
            "hosts": {
                "local": {
                    "type": "podman-machine",
                    "machine": "podman-machine-default",
                }
            },
            "projects": {
                "devspace": {
                    "host": [{"name": "local"}],
                    "provider": "github",
                    "repo": "owner/repo",
                }
            },
        }
    )

    options = config.host_config("local")
    assert options.type == "podman-machine"
    assert options.machine == "podman-machine-default"

    with pytest.raises(ValueError, match="discovered from machine inspect"):
        config.host_config("local").resolved_podman_socket()


def test_config_accepts_inherited_environment_for_ssh_host() -> None:
    config = Config.model_validate(
        {
            "default_image": "img",
            "container": _CONTAINER,
            "hosts": {
                "home": {
                    "environment": ["HTTP_PROXY", "_INTERNAL_TOKEN"],
                }
            },
            "projects": {
                "devspace": {
                    "host": [{"name": "home"}],
                    "provider": "github",
                    "repo": "owner/repo",
                }
            },
        }
    )

    assert config.host_config("home").environment == ["HTTP_PROXY", "_INTERNAL_TOKEN"]


@pytest.mark.parametrize("name", ["", "1INVALID", "INVALID-NAME", "INVALID.NAME"])
def test_config_rejects_invalid_inherited_environment_name(name: str) -> None:
    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        Config.model_validate(
            {
                "default_image": "img",
                "container": _CONTAINER,
                "hosts": {"home": {"environment": [name]}},
                "projects": {
                    "devspace": {
                        "host": [{"name": "home"}],
                        "provider": "github",
                        "repo": "owner/repo",
                    }
                },
            }
        )


def test_config_rejects_duplicate_or_reserved_inherited_environment() -> None:
    base = {
        "default_image": "img",
        "container": _CONTAINER,
        "projects": {
            "devspace": {
                "host": [{"name": "home"}],
                "provider": "github",
                "repo": "owner/repo",
            }
        },
    }
    with pytest.raises(ValidationError, match="must not contain duplicates"):
        Config.model_validate(
            {
                **base,
                "hosts": {"home": {"environment": ["HTTP_PROXY", "HTTP_PROXY"]}},
            }
        )
    with pytest.raises(ValidationError, match="must not inherit control-plane keys"):
        Config.model_validate(
            {
                **base,
                "hosts": {"home": {"environment": ["SSHD_PORT"]}},
            }
        )


def test_config_rejects_inherited_environment_for_podman_machine() -> None:
    with pytest.raises(ValidationError, match="only valid for SSH hosts"):
        Config.model_validate(
            {
                "default_image": "img",
                "container": _CONTAINER,
                "hosts": {
                    "local": {
                        "type": "podman-machine",
                        "machine": "podman-machine-default",
                        "environment": ["HTTP_PROXY"],
                    }
                },
                "projects": {
                    "devspace": {
                        "host": [{"name": "local"}],
                        "provider": "github",
                        "repo": "owner/repo",
                    }
                },
            }
        )


def test_config_rejects_collision_between_inherited_and_explicit_environment() -> None:
    with pytest.raises(ValidationError, match="inherited host environment variables"):
        Config.model_validate(
            {
                "default_image": "img",
                "container": {
                    **_CONTAINER,
                    "environment": {"HTTP_PROXY": "http://configured:3128"},
                },
                "hosts": {"home": {"environment": ["HTTP_PROXY"]}},
                "projects": {
                    "devspace": {
                        "host": [{"name": "home"}],
                        "provider": "github",
                        "repo": "owner/repo",
                    }
                },
            }
        )


def test_config_ssh_host_uses_host_network() -> None:
    config = Config.model_validate(
        {
            "default_image": "img",
            "container": _CONTAINER,
            "hosts": {"home": _SSH_HOST},
            "projects": {
                "devspace": {"host": [{"name": "home"}], "provider": "github", "repo": "owner/repo"}
            },
        }
    )

    assert config.host_config("home").type == "ssh"
    assert config.resolved_container("devspace", "home").is_bridge is False
    assert config.resolved_container("devspace", "home").network_mode == "host"


def test_config_bridge_via_host_container_enables_port_publishing() -> None:
    """network_mode lives in the container block and can be set per host override."""
    config = Config.model_validate(
        {
            "default_image": "img",
            "container": _CONTAINER,
            "hosts": {"home": {"container": {"network_mode": "bridge"}}},
            "projects": {
                "devspace": {
                    "host": [{"name": "home"}],
                    "provider": "github",
                    "repo": "owner/repo",
                    "published_ports": ["8080"],
                }
            },
        }
    )

    assert config.host_config("home").type == "ssh"
    assert config.resolved_container("devspace", "home").is_bridge is True
    assert config.project_ports("devspace") == [(8080, 8080)]


def _bridge_machine_project_config(published_ports: list[str]) -> dict[str, object]:
    return {
        "default_image": "img",
        "container": _CONTAINER,
        "hosts": {
            "local": {
                "type": "podman-machine",
                "machine": "podman-machine-default",
                "container": {"network_mode": "bridge"},
            },
        },
        "projects": {
            "devspace": {
                "host": [{"name": "local"}],
                "provider": "github",
                "repo": "owner/repo",
                "published_ports": published_ports,
            }
        },
    }


def test_config_parses_project_ports_on_bridge_host() -> None:
    config = Config.model_validate(_bridge_machine_project_config(["8080", "3000:5000"]))

    assert config.project_ports("devspace") == [(8080, 8080), (3000, 5000)]


def test_config_rejects_ports_on_host_network_host() -> None:
    with pytest.raises(ValidationError, match="port publishing requires bridge mode"):
        Config.model_validate(
            {
                "default_image": "img",
                "container": _CONTAINER,
                "hosts": {"home": _SSH_HOST},
                "projects": {
                    "devspace": {
                        "host": [{"name": "home"}],
                        "provider": "github",
                        "repo": "owner/repo",
                        "published_ports": ["8080"],
                    }
                },
            }
        )


def test_config_rejects_malformed_port_mapping() -> None:
    with pytest.raises(ValidationError, match="not a port number"):
        Config.model_validate(_bridge_machine_project_config(["http"]))


def test_config_rejects_out_of_range_port() -> None:
    with pytest.raises(ValidationError, match="between 1 and 65535"):
        Config.model_validate(_bridge_machine_project_config(["70000"]))


def test_config_rejects_duplicate_published_host_port() -> None:
    with pytest.raises(ValidationError, match="duplicate published host port"):
        Config.model_validate(_bridge_machine_project_config(["8080", "8080:9090"]))


def test_config_project_ports_defaults_empty() -> None:
    config = Config.model_validate(
        {
            "default_image": "img",
            "container": _CONTAINER,
            "hosts": {"home": _SSH_HOST},
            "projects": {
                "devspace": {"host": [{"name": "home"}], "provider": "github", "repo": "owner/repo"}
            },
        }
    )

    assert config.project_ports("devspace") == []


def test_config_resolved_container_uses_global_defaults(config: Config) -> None:
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


def test_config_resolved_container_applies_host_and_project_overrides() -> None:
    config = Config.model_validate(
        {
            "default_image": "img",
            "container": {
                "network_mode": "host",
                "cap_add": ["NET_RAW"],
                "security_opt": ["disable"],
                "pids_limit": -1,
                "ulimits": {},
                "environment": {"BASE": "1"},
            },
            "hosts": {
                "home": {
                    "container": {
                        "cap_add": ["NET_RAW", "SYS_ADMIN"],
                        "pids_limit": 100,
                    },
                }
            },
            "projects": {
                "devspace": {
                    "host": [{"name": "home"}],
                    "provider": "github",
                    "repo": "owner/repo",
                    "container": {
                        "pids_limit": 200,
                        "environment": {"PROJECT": "1"},
                    },
                }
            },
        }
    )

    resolved = config.resolved_container("devspace", "home")

    # host override replaces cap_add wholesale; project override wins on pids_limit
    assert resolved.cap_add == ["NET_RAW", "SYS_ADMIN"]
    assert resolved.pids_limit == 200
    # environment is replaced wholesale by the project layer, not deep-merged
    assert resolved.environment == {"PROJECT": "1"}
    # security_opt untouched by any override, inherits global
    assert resolved.security_opt == ["disable"]


def test_config_rejects_reserved_container_env_key() -> None:
    with pytest.raises(ValidationError, match="control-plane keys"):
        Config.model_validate(
            {
                "default_image": "img",
                "container": {
                    "cap_add": [],
                    "security_opt": [],
                    "pids_limit": -1,
                    "ulimits": {},
                    "environment": {"SSHD_PORT": "2222"},
                },
                "hosts": {"home": _SSH_HOST},
                "projects": {
                    "devspace": {
                        "host": [{"name": "home"}],
                        "provider": "github",
                        "repo": "owner/repo",
                    }
                },
            }
        )


def test_config_rejects_relative_container_volume_source() -> None:
    with pytest.raises(ValidationError, match="must be an absolute path"):
        Config.model_validate(
            {
                "default_image": "img",
                "container": {
                    "cap_add": [],
                    "security_opt": [],
                    "pids_limit": -1,
                    "ulimits": {},
                    "volumes": [{"source": "relative", "target": "/etc/x"}],
                },
                "hosts": {"home": _SSH_HOST},
                "projects": {
                    "devspace": {
                        "host": [{"name": "home"}],
                        "provider": "github",
                        "repo": "owner/repo",
                    }
                },
            }
        )


@pytest.mark.parametrize(
    "target",
    [
        "/workspace",
        "/workspace/cache",
        "/workspace/../workspace",
        "/upload",
        "/upload/incoming",
        "/",
    ],
)
def test_config_rejects_control_plane_mount_target_overlap(target: str) -> None:
    with pytest.raises(ValidationError, match="control-plane mount targets"):
        Config.model_validate(
            {
                "default_image": "img",
                "container": {
                    **_CONTAINER,
                    "volumes": [{"source": "/host/data", "target": target}],
                },
                "hosts": {"home": _SSH_HOST},
                "projects": {
                    "devspace": {
                        "host": [{"name": "home"}],
                        "provider": "github",
                        "repo": "owner/repo",
                    }
                },
            }
        )


@pytest.mark.parametrize("target", ["/workspace-old", "/uploads", "/etc/data"])
def test_config_allows_mount_targets_outside_control_plane_paths(target: str) -> None:
    config = Config.model_validate(
        {
            "default_image": "img",
            "container": {
                **_CONTAINER,
                "volumes": [{"source": "/host/data", "target": target}],
            },
            "hosts": {"home": _SSH_HOST},
            "projects": {
                "devspace": {
                    "host": [{"name": "home"}],
                    "provider": "github",
                    "repo": "owner/repo",
                }
            },
        }
    )

    volumes = config.resolved_container("devspace", "home").volumes
    assert volumes is not None
    assert volumes[0].target == target


def _config_with_container(container: dict[str, object]) -> dict[str, object]:
    return {
        "default_image": "img",
        "container": {**_CONTAINER, **container},
        "hosts": {"home": _SSH_HOST},
        "projects": {
            "devspace": {
                "host": [{"name": "home"}],
                "provider": "github",
                "repo": "owner/repo",
            }
        },
    }


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


def test_config_rejects_secret_mount_target_overlapping_control_plane() -> None:
    with pytest.raises(ValidationError, match="control-plane mount targets"):
        Config.model_validate(
            _config_with_container({"secrets": [{"source": "a", "target": "/workspace/secret"}]})
        )


def test_config_rejects_secret_env_target_colliding_with_inherited_host_env() -> None:
    with pytest.raises(ValidationError, match=r"as container\.secrets env target"):
        Config.model_validate(
            {
                "default_image": "img",
                "container": {
                    **_CONTAINER,
                    "secrets": [{"source": "a", "mode": "env", "target": "HTTP_PROXY"}],
                },
                "hosts": {"home": {"environment": ["HTTP_PROXY"]}},
                "projects": {
                    "devspace": {
                        "host": [{"name": "home"}],
                        "provider": "github",
                        "repo": "owner/repo",
                    }
                },
            }
        )


def test_config_seeds_tokens_from_tokens_table(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        f"""
default_image: "default:latest"
{_CONTAINER_YAML}
hosts:
  home:

projects:
  devspace:
    host:
      - name: home
    repo: "github:curoky/devspace"

tokens:
  github: "ghp_example"
""",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.seed_tokens() == {"github": "ghp_example"}
    assert "ghp_example" not in repr(config)


def test_config_seed_tokens_defaults_to_empty() -> None:
    config = Config.model_validate(
        {
            "default_image": "img",
            "container": _CONTAINER,
            "hosts": {"home": _SSH_HOST},
            "projects": {
                "devspace": {
                    "host": [{"name": "home"}],
                    "provider": "github",
                    "repo": "owner/repo",
                }
            },
        }
    )

    assert config.seed_tokens() == {}


@pytest.mark.parametrize("provider", ["github", "gitlab"])
def test_config_rejects_blank_token(provider: str) -> None:
    with pytest.raises(ValidationError, match="token must not be blank"):
        Config.model_validate(
            {
                "default_image": "img",
                "container": _CONTAINER,
                "hosts": {"home": _SSH_HOST},
                "projects": {
                    "devspace": {
                        "host": [{"name": "home"}],
                        "provider": "github",
                        "repo": "owner/repo",
                    }
                },
                "tokens": {provider: "   "},
            }
        )


@pytest.mark.parametrize(
    ("host_options", "message"),
    [
        ({"podman_socket": "relative.sock"}, "absolute path"),
        (
            {"type": "podman-machine"},
            "machine is required",
        ),
        (
            {
                "type": "podman-machine",
                "machine": "podman-machine-default",
                "podman_socket": "/run/podman/podman.sock",
            },
            "podman_socket is not valid",
        ),
        (
            {"machine": "podman-machine-default"},
            "machine is only valid",
        ),
        ({"unknown": "x"}, "Extra inputs"),
    ],
)
def test_config_rejects_invalid_host_options(
    host_options: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        Config.model_validate(
            {
                "default_image": "img",
                "container": _CONTAINER,
                "hosts": {"home": host_options},
                "projects": {
                    "devspace": {
                        "host": [{"name": "home"}],
                        "provider": "github",
                        "repo": "owner/repo",
                    }
                },
            }
        )


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (
            {
                "default_image": "img",
                "container": _CONTAINER,
                "hosts": {},
                "projects": {
                    "project": {
                        "host": [{"name": "home"}],
                        "provider": "github",
                        "repo": "owner/repo",
                    }
                },
            },
            "at least one host",
        ),
        (
            {
                "default_image": "img",
                "container": _CONTAINER,
                "hosts": {"home": _SSH_HOST},
                "projects": {
                    "Bad": {
                        "host": [{"name": "home"}],
                        "provider": "github",
                        "repo": "owner/repo",
                    }
                },
            },
            "project 'Bad'",
        ),
        (
            {
                "default_image": "img",
                "container": _CONTAINER,
                "hosts": {"home": _SSH_HOST},
                "projects": {
                    "project": {
                        "host": [{"name": "office"}],
                        "provider": "github",
                        "repo": "owner/repo",
                    }
                },
            },
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


@pytest.mark.parametrize("missing", ["default_image", "hosts", "projects"])
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
    assert spec.workspace_path("/home/x/codespace") == "/home/x/codespace/devspace/debug"
    assert ssh_port(identity) == ssh_port(identity)
    assert 20_000 <= ssh_port(identity) <= 29_999
