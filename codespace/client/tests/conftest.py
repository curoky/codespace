"""Shared fixtures for the rewritten local Codespace control plane."""

from __future__ import annotations

import pytest

from codespace.client.config import Config


@pytest.fixture
def config() -> Config:
    return Config.model_validate(
        {
            "default_image": "ghcr.io/curoky/devspace:codespace-debian13",
            "hosts": {"home": None, "office": None},
            "projects": {
                "devspace": {
                    "host": "home",
                    "provider": "github",
                    "repo": "curoky/devspace",
                    "description": "Devspace repository",
                    "platform": "linux/arm64",
                },
                "service-api": {
                    "host": "office",
                    "provider": "gitlab",
                    "repo": "group/service-api",
                    "image": "registry.example.com/codespace-api:latest",
                },
            },
        }
    )
