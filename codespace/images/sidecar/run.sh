#!/usr/bin/env bash

set -euo pipefail

readonly container_name=codespace-sidecar
readonly image=ghcr.io/curoky/devspace:codespace-sidecar

podman pull "${image}"

if podman container exists "${container_name}"; then
  podman rm -f "${container_name}" >/dev/null
fi

podman run --detach \
  --name "${container_name}" \
  --network host \
  --restart unless-stopped \
  --env ATUIN_DB_URI="${ATUIN_DB_URI:?ATUIN_DB_URI is required}" \
  "${image}"

echo "sidecar '${container_name}' started."
