"""Shared fixtures for the rewritten local Codespace control plane."""

from __future__ import annotations

import pytest

from controller.config import Config


@pytest.fixture
def config() -> Config:
    return Config.model_validate(
        {
            "default_image": "ghcr.io/curoky/devspace:codespace-debian13",
            "container": {
                "network_mode": "host",
                "cap_add": ["NET_RAW", "SYS_ADMIN"],
                "security_opt": ["disable", "seccomp=unconfined"],
                "pids_limit": -1,
                "ulimits": {"memlock": {"soft": -1, "hard": -1}},
                "volumes": ["/etc/krb5.conf:/etc/krb5.conf:ro"],
            },
            "hosts": {
                "home": {},
                "office": {},
            },
            "projects": {
                "devspace": {
                    "host": [{"name": "home", "platform": "linux/arm64"}],
                    "provider": "github",
                    "repo": "curoky/devspace",
                    "description": "Devspace repository",
                },
                "service-api": {
                    "host": [{"name": "office"}],
                    "provider": "gitlab",
                    "repo": "group/service-api",
                    "image": "registry.example.com/codespace-api:latest",
                },
                "scratch": {
                    "host": [{"name": "home"}],
                    "type": "blank",
                    "description": "Repo-less scratch space",
                },
            },
        }
    )
