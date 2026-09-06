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
                    "cap_add": ["NET_RAW", "SYS_ADMIN"],
                    "security_opt": ["disable", "seccomp=unconfined"],
                    "pids_limit": -1,
                    "ulimits": {"memlock": {"soft": -1, "hard": -1}},
                    "volumes": [
                        "/etc/krb5.conf:/etc/krb5.conf:ro",
                        "${RESOURCE_DATA}/workspace:/workspace",
                        "${RESOURCE_DATA}/upload:/upload",
                        "${RESOURCE_DATA}/control:/run/codespace-control",
                        "${RESOURCE_DATA}/cache/.vscode-server/bin:/home/x/.vscode-server/bin",
                        "${RESOURCE_DATA}/cache/.vscode-server/extensions:/home/x/.vscode-server/extensions",
                        "${RESOURCE_DATA}/cache/.trae/bin:/home/x/.trae/bin",
                        "${RESOURCE_DATA}/cache/.trae/extensions:/home/x/.trae/extensions",
                        "${RESOURCE_DATA}/cache/.trae-cn/bin:/home/x/.trae-cn/bin",
                        "${RESOURCE_DATA}/cache/.trae-cn/extensions:/home/x/.trae-cn/extensions",
                        "${RESOURCE_DATA}/cache/.trae-server/bin:/home/x/.trae-server/bin",
                        "${RESOURCE_DATA}/cache/.trae-server/extensions:/home/x/.trae-server/extensions",
                        "${RESOURCE_DATA}/cache/.trae-cn-server/bin:/home/x/.trae-cn-server/bin",
                        "${RESOURCE_DATA}/cache/.trae-cn-server/extensions:/home/x/.trae-cn-server/extensions",
                    ],
                },
            },
            "projects": {
                "codespace": {
                    "description": "Personal development platform",
                    "source": {
                        "type": "github",
                        "repository": "curoky/codespace",
                    },
                    "hosts": ["home"],
                },
                "service-api": {
                    "source": {
                        "type": "gitlab",
                        "repository": "group/service-api",
                    },
                    "hosts": ["office"],
                    "image": "registry.example.com/workspace-api:latest",
                },
                "scratch": {
                    "source": {"type": "empty"},
                    "hosts": ["home"],
                },
                "personal": {
                    "source": {
                        "type": "git",
                        "url": "git@github.com:curoky/codespace.git",
                    },
                    "hosts": ["home"],
                },
            },
            "services": {
                "support": {
                    "image": "ghcr.io/curoky/codespace:service-support",
                    "hosts": ["home"],
                },
                "vllm": {
                    "image": "ghcr.io/curoky/codespace:service-vllm",
                    "hosts": ["office"],
                    "container": {
                        "ipc": "host",
                        "devices": ["nvidia.com/gpu=all"],
                        "volumes": [
                            "${RESOURCE_DATA}:/root/.cache/huggingface",
                        ],
                    },
                },
            },
        }
    )
