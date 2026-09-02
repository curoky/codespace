#!/usr/bin/env bash

# Build the SGLang Qwen3.8-Flash-Next-FP8 serving image from the repo root.
# Produces ghcr.io/curoky/devspace:deployments-sglang. Weights are not baked in (see
# images/deployments/sglang/AGENTS.md).

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../../.."

docker build . --network=host --file images/deployments/sglang/Dockerfile \
  --tag ghcr.io/curoky/devspace:deployments-sglang
