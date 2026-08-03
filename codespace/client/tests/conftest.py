"""Shared fixtures for the rewritten local Codespace control plane."""

from __future__ import annotations

import pytest

from codespace.client.config import Config


@pytest.fixture
def config() -> Config:
    return Config.model_validate(
        {
            "default_image": "ghcr.io/curoky/devspace:codespace-debian13",
            "container": {
                "cap_add": ["NET_RAW", "SYS_ADMIN"],
                "security_opt": ["disable", "seccomp=unconfined"],
                "pids_limit": -1,
                "ulimits": [{"name": "memlock", "soft": -1, "hard": -1}],
                "mounts": [
                    {
                        "source": "/etc/krb5.conf",
                        "target": "/etc/krb5.conf",
                        "read_only": True,
                    }
                ],
            },
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
                "scratch": {
                    "host": "home",
                    "type": "blank",
                    "description": "Repo-less scratch space",
                },
            },
        }
    )
