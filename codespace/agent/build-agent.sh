#!/usr/bin/env bash

# Build the codespace agent image from the repo root so pyproject.toml/uv.lock
# are in the build context (see codespace/agent/Dockerfile).

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

podman build \
	-t ghcr.io/curoky/devspace:codespace-agent \
	-f codespace/agent/Dockerfile \
	.
