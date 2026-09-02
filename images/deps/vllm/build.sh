#!/usr/bin/env bash

# Build vLLM from source for 8x H100 (SM 9.0) against CUDA 12.9, from the repo
# root. Produces
# ghcr.io/curoky/devspace:deps-vllm0.28-cu12.9.1-cudnn9-gcc12-py3.12.
# Pass a combo name as $1 to build another variant, e.g. the cu13 one.
# See images/deps/AGENTS.md for the naming scheme and build constraints.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../../.."

combo=${1:-vllm0.28-cu12.9.1-cudnn9-gcc12-py3.12}

# 构建实际在远端 rootful podman host（192 核 / 317GB RAM）上执行，本瘦客户端
# 容器的 3GB 限制不影响它，故默认高并发；内存受限的 host 可用环境变量覆盖调小。
MAX_JOBS=${MAX_JOBS:-48}
NVCC_THREADS=${NVCC_THREADS:-4}

docker build . --network=host \
  --build-arg "MAX_JOBS=${MAX_JOBS}" --build-arg "NVCC_THREADS=${NVCC_THREADS}" \
  --file "images/deps/vllm/${combo}.Dockerfile" \
  --tag "ghcr.io/curoky/devspace:deps-${combo}"
