#!/usr/bin/env bash

# Build the vLLM Qwen3.8-Flash-Next-FP8 serving image from the repo root.
# Produces ghcr.io/curoky/devspace:llm-vllm. Weights are not baked in (see
# images/llm/AGENTS.md).

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../../.."

docker build . --network=host --file images/llm/vllm/Dockerfile \
  --tag ghcr.io/curoky/devspace:llm-vllm
