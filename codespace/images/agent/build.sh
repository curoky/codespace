#!/usr/bin/env bash

# Build the codespace agent image from the repo root so pyproject.toml/uv.lock
# are in the build context (see codespace/images/agent/Dockerfile).

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../../.."

docker build . --network=host --file codespace/images/agent/Dockerfile \
	--tag ghcr.io/curoky/devspace:codespace-agent
