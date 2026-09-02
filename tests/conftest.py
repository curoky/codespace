"""Shared fixtures for the Codespace control plane."""

from __future__ import annotations

import pytest

from codespace.config import Config


@pytest.fixture
def config() -> Config:
    return Config.model_validate(
        {
            "hosts": {
                "home": {
                    "forward_environment": ["HTTP_PROXY"],
                    "platform": "linux/arm64",
                },
                "office": {},
            },
            "project_defaults": {
                "image": "ghcr.io/curoky/codespace:workspace-debian13",
                "container": {
                    "network_mode": "host",
                    "cap_add": ["NET_RAW", "SYS_ADMIN"],
                    "security_opt": ["disable", "seccomp=unconfined"],
                    "pids_limit": -1,
                    "ulimits": {"memlock": {"soft": -1, "hard": -1}},
                    "volumes": ["/etc/krb5.conf:/etc/krb5.conf:ro"],
                },
            },
            "projects": {
                "codespace": {
                    "description": "Personal development platform",
                    "source": {
                        "type": "github",
                        "repository": "curoky/codespace",
                    },
                    "hosts": {
                        "home": {},
                    },
                },
                "service-api": {
                    "source": {
                        "type": "gitlab",
                        "repository": "group/service-api",
                    },
                    "hosts": {"office": {}},
                    "image": "registry.example.com/workspace-api:latest",
                },
                "scratch": {
                    "source": {"type": "empty"},
                    "hosts": {"home": {}},
                },
                "personal": {
                    "source": {
                        "type": "git",
                        "url": "git@github.com:curoky/codespace.git",
                    },
                    "hosts": {"home": {}},
                },
            },
            "services": {
                "support": {
                    "image": "ghcr.io/curoky/codespace:service-support",
                    "hosts": {"home": {}},
                    "container": {"network_mode": "host"},
                },
                "vllm": {
                    "image": "ghcr.io/curoky/codespace:service-vllm",
                    "hosts": {"office": {}},
                    "container": {
                        "network_mode": "host",
                        "ipc": "host",
                        "devices": ["nvidia.com/gpu=all"],
                        "volumes": [
                            "${SERVICE_DATA}:/root/.cache/huggingface",
                        ],
                    },
                },
            },
        }
    )
