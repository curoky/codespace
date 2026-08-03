"""Tests for strict YAML configuration and deterministic resource identity."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from codespace.client.config import Config, load_config
from codespace.client.models import (
    CreateInstanceRequest,
    environment_id,
    ssh_port,
    workspace_path,
)


def test_load_config_reads_yaml_and_resolves_image(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        """
default_image: "default:latest"
hosts:
  home:
  office:

projects:
  devspace:
    host: "home"
    repo: "github:curoky/devspace"
  service-api:
    host: "office"
    repo: "gitlab:group/service-api"
    image: "custom:latest"
    platform: "linux/arm64"
""",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.project_image("devspace") == "default:latest"
    assert config.project_image("service-api") == "custom:latest"
    assert config.projects["devspace"].provider == "github"
    assert config.projects["devspace"].repo == "curoky/devspace"
    assert config.projects["service-api"].provider == "gitlab"
    assert config.projects["devspace"].platform is None
    assert config.projects["service-api"].platform == "linux/arm64"


def test_config_rejects_invalid_project_platform(config: Config) -> None:
    data = config.model_dump()
    data["projects"]["devspace"]["platform"] = "linux/riscv64"

    with pytest.raises(ValidationError, match=r"linux/amd64.*linux/arm64"):
        Config.model_validate(data)


def test_config_rejects_combined_repo_with_separate_provider() -> None:
    with pytest.raises(ValidationError, match="either combined 'repo' or separate 'provider'"):
        Config.model_validate(
            {
                "default_image": "img",
                "hosts": {"home": None},
                "projects": {
                    "devspace": {
                        "host": "home",
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
            "hosts": {"home": None},
            "projects": {
                "scratch": {
                    "host": "home",
                    "type": "blank",
                },
                "notes": {
                    "host": "home",
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
                "hosts": {"home": None},
                "projects": {
                    "scratch": {
                        "host": "home",
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
                "hosts": {"home": None},
                "projects": {"devspace": {"host": "home", "type": "repo"}},
            }
        )


def test_config_rejects_relative_open_path() -> None:
    with pytest.raises(ValidationError, match="open_path must be an absolute path"):
        Config.model_validate(
            {
                "default_image": "img",
                "hosts": {"home": None},
                "projects": {
                    "scratch": {
                        "host": "home",
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
            "hosts": {
                "home": None,
                "office": {"podman_socket": "/tmp/podmanxd.sock"},
            },
            "projects": {
                "devspace": {
                    "host": "home",
                    "provider": "github",
                    "repo": "owner/repo",
                }
            },
        }
    )

    assert config.podman_socket("office") == "/tmp/podmanxd.sock"
    assert config.podman_socket("home") == "/run/podman/podman.sock"
    assert config.host_config("home").type == "ssh"
    assert config.host_config("office").podman_socket == "/tmp/podmanxd.sock"


def test_config_accepts_explicit_podman_machine_host() -> None:
    config = Config.model_validate(
        {
            "default_image": "img",
            "hosts": {
                "local": {
                    "type": "podman-machine",
                    "machine": "podman-machine-default",
                }
            },
            "projects": {
                "devspace": {
                    "host": "local",
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
        config.podman_socket("local")


def test_config_seeds_tokens_from_tokens_table(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        """
default_image: "default:latest"
hosts:
  home:

projects:
  devspace:
    host: "home"
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
            "hosts": {"home": None},
            "projects": {
                "devspace": {
                    "host": "home",
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
                "hosts": {"home": None},
                "projects": {
                    "devspace": {
                        "host": "home",
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
                "hosts": {"home": host_options},
                "projects": {
                    "devspace": {
                        "host": "home",
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
                "hosts": {},
                "projects": {
                    "project": {
                        "host": "home",
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
                "hosts": {"home": None},
                "projects": {
                    "Bad": {
                        "host": "home",
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
                "hosts": {"home": None},
                "projects": {
                    "project": {
                        "host": "office",
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
    assert CreateInstanceRequest(instance=instance).instance == instance


@pytest.mark.parametrize("instance", ["Debug", "-bad", "bad_name", "x" * 33, ""])
def test_create_request_rejects_invalid_instance(instance: str) -> None:
    with pytest.raises(ValidationError):
        CreateInstanceRequest(instance=instance)


def test_resource_identity_contract_is_deterministic() -> None:
    identity = environment_id("home", "devspace", "debug")

    assert identity == "codespace-home-devspace-debug"
    assert (
        workspace_path("/home/x/codespace2", "devspace", "debug")
        == "/home/x/codespace2/devspace/debug"
    )
    assert ssh_port(identity) == ssh_port(identity)
    assert 20_000 <= ssh_port(identity) <= 29_999
