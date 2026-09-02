"""Shared fixtures for the Codespace control plane."""

from __future__ import annotations

import pytest

from codespace.config import Config


@pytest.fixture
def config() -> Config:
    return Config.model_validate(
        {
            "hosts": {
                "home": {"forward_environment": ["HTTP_PROXY"]},
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
                    "volumes": {
                        "kerberos": {
                            "source": "/etc/krb5.conf",
                            "target": "/etc/krb5.conf",
                            "read_only": True,
                        }
                    },
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
                        "home": {"platform": "linux/arm64"},
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
                        "volumes": {
                            "models": {
                                "source": "${SERVICE_DATA}",
                                "target": "/root/.cache/huggingface",
                            }
                        },
                    },
                },
            },
        }
    )
