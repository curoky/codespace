"""Tests for strict TOML configuration and deterministic resource identity."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from codespace.client.config import Config, load_config
from codespace.client.models import (
    CreateInstanceRequest,
    deploy_key_title,
    environment_id,
    ssh_port,
    workspace_path,
)


def test_load_config_reads_toml_and_resolves_image(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
default_image = "default:latest"
hosts = ["home", "office"]

[projects.devspace]
host = "home"
provider = "github"
repo = "curoky/devspace"

[projects.service-api]
host = "office"
provider = "gitlab"
repo = "group/service-api"
image = "custom:latest"
""",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.project_image("devspace") == "default:latest"
    assert config.project_image("service-api") == "custom:latest"


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (
            {
                "default_image": "img",
                "hosts": ["home", "home"],
                "projects": {
                    "project": {
                        "host": "home",
                        "provider": "github",
                        "repo": "owner/repo",
                    }
                },
            },
            "duplicates",
        ),
        (
            {
                "default_image": "img",
                "hosts": ["home"],
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
                "hosts": ["home"],
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
    assert deploy_key_title(identity) == identity
    assert workspace_path("devspace", "debug") == "/var/lib/codespace/devspace/debug"
    assert ssh_port(identity) == ssh_port(identity)
    assert 20_000 <= ssh_port(identity) <= 29_999
