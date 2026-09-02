#!/usr/bin/env bash

# Smoke launcher for the host-level vLLM Service. It creates the same
# deterministic, inventory-visible container as the control plane.

set -euo pipefail

if (($# != 0)); then
  echo "Usage: $0" >&2
  exit 2
fi

service="vllm"
name="codespace-service-${service}"
image="ghcr.io/curoky/codespace:service-${service}"
port="${SERVE_PORT:-8003}"
listen_host="${SERVE_HOST:-127.0.0.1}"
hf_home="${HF_HOME:-${HOME}/codespace/services/${service}}"

mkdir -p -- "${hf_home}"

podman pull "${image}"

# The two engines consume all GPUs and share the API port, so starting either
# one replaces any existing inference Service.
for existing_name in codespace-service-vllm codespace-service-sglang; do
  if podman container exists "${existing_name}"; then
    podman rm -f "${existing_name}" >/dev/null
  fi
done

podman_args=(
  run
  --detach
  --name "${name}"
  --network host
  --restart unless-stopped
  --device nvidia.com/gpu=all
  --ipc host
  --volume "${hf_home}:/root/.cache/huggingface"
  --env "HF_HOME=/root/.cache/huggingface"
  --env "SERVE_HOST=${listen_host}"
  --env "SERVE_PORT=${port}"
  --env "SERVE_MODEL=${SERVE_MODEL:-Qwen/Qwen3.8-Flash-Next-FP8}"
  --env "SERVE_EXTRA_ARGS=${SERVE_EXTRA_ARGS:-}"
  --label codespace.kind=service
  --label "codespace.service=${service}"
  --label "codespace.image=${image}"
)

if [[ -n "${HF_TOKEN:-}" ]]; then
  podman_args+=(--env "HF_TOKEN=${HF_TOKEN}")
fi
if [[ -n "${VLLM_PLE_CPU_OFFLOAD:-}" ]]; then
  podman_args+=(--env "VLLM_PLE_CPU_OFFLOAD=${VLLM_PLE_CPU_OFFLOAD}")
fi

podman "${podman_args[@]}" "${image}"

echo "Service '${service}' is starting on http://${listen_host}:${port}."
echo "Watch startup with: podman logs -f ${name}"
