#!/usr/bin/env bash

# Direct launcher for the host-level SGLang deployment. The controller remains
# the normal lifecycle owner; this script is useful when operating on the GPU
# host itself and creates the same deterministic, inventory-visible container.

set -euo pipefail

deployment="sglang"
name="codespace-${deployment}"
image="ghcr.io/curoky/devspace:deployments-${deployment}"
port="${SERVE_PORT:-8003}"
listen_host="${SERVE_HOST:-127.0.0.1}"
hf_home="${HF_HOME:-${HOME}/codespace/deployments/${deployment}}"

mkdir -p "${hf_home}"

podman pull "${image}"

# The two engines consume all GPUs and share the API port, so starting either
# one replaces any existing serving deployment.
for existing_name in codespace-vllm codespace-sglang; do
  if podman container exists "${existing_name}"; then
    podman rm -f "${existing_name}" >/dev/null
  fi
done

optional_env_args=()
if [[ -n "${HF_TOKEN:-}" ]]; then
  optional_env_args+=(--env "HF_TOKEN=${HF_TOKEN}")
fi

podman run --detach \
  --name "${name}" \
  --network host \
  --restart unless-stopped \
  --device nvidia.com/gpu=all \
  --ipc host \
  --volume "${hf_home}:/root/.cache/huggingface" \
  --env "HF_HOME=/root/.cache/huggingface" \
  --env "SERVE_HOST=${listen_host}" \
  --env "SERVE_PORT=${port}" \
  --env "SERVE_MODEL=${SERVE_MODEL:-Qwen/Qwen3.8-Flash-Next-FP8}" \
  --env "SERVE_EXTRA_ARGS=${SERVE_EXTRA_ARGS:-}" \
  --label codespace.deployment=true \
  --label "codespace.deployment-id=${deployment}" \
  --label "codespace.image=${image}" \
  "${optional_env_args[@]}" \
  "${image}"

echo "Deployment '${deployment}' is starting on http://${listen_host}:${port}."
echo "Watch startup with: podman logs -f ${name}"
