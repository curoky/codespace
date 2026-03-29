#!/usr/bin/env bash

# Launch the single host-level SGLang Qwen3.8-Flash-Next-FP8 serving container on
# a single 8x H100 node. Mirrors the sidecar launcher shape: fixed container name,
# restart policy, and OpenAI API published to host loopback only.
#
# Unlike the sidecar, this container needs all local GPUs and a large weight
# cache, so it bind-mounts the host Hugging Face cache and requests every GPU via
# CDI. The ~172 GiB FP8 weights are pulled by the engine on first start into that
# cache; no weights are baked into the image.
#
# Host prerequisites:
#   - NVIDIA Container Toolkit with CDI configured (nvidia.com/gpu device).
#   - A Hugging Face cache dir with enough free space (>= ~200 GiB); override
#     with HF_HOME. For gated/faster downloads, export HF_TOKEN before running.
#
# Topology: 8x H100 FP8 requires TEP8 (TP8 + expert parallel); serve.sh enables
# it by default via --ep-size. If the load OOMs, lower MAX_MODEL_LEN or
# GPU_MEM_UTIL.

set -euo pipefail

name="codespace-llm"
image="ghcr.io/curoky/devspace:llm-sglang"
port="${LLM_PORT:-8003}"
hf_home="${HF_HOME:-${HOME}/.cache/huggingface}"

mkdir -p "${hf_home}"

podman pull "${image}"

if podman container exists "${name}"; then
  podman rm -f "${name}" >/dev/null
fi

hf_token_args=()
if [[ -n "${HF_TOKEN:-}" ]]; then
  hf_token_args=(--env "HF_TOKEN=${HF_TOKEN}")
fi

podman run --detach \
  --name "${name}" \
  --network bridge \
  --publish "127.0.0.1:${port}:${port}" \
  --restart unless-stopped \
  --device nvidia.com/gpu=all \
  --ipc host \
  --shm-size 32g \
  --volume "${hf_home}:/root/.cache/huggingface" \
  --env "HF_HOME=/root/.cache/huggingface" \
  --env "LLM_PORT=${port}" \
  --env "TP_SIZE=${TP_SIZE:-8}" \
  --env "EP_SIZE=${EP_SIZE:-8}" \
  --env "MAX_MODEL_LEN=${MAX_MODEL_LEN:-262144}" \
  "${hf_token_args[@]}" \
  "${image}"

echo "llm '${name}' (sglang) starting on http://127.0.0.1:${port}."
echo "first start downloads ~172 GiB FP8 weights into ${hf_home}; watch: podman logs -f ${name}"
