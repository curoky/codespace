#!/usr/bin/env bash

set -euo pipefail

if (($# != 0)); then
  echo "Usage: $0" >&2
  exit 2
fi

service="chatbox"
name="codespace-service-${service}"
image="ghcr.io/curoky/codespace:service-${service}"
port="${CHATBOX_PORT:-3212}"
api_upstream="${CHATBOX_API_UPSTREAM:-http://10.88.0.1:8003}"

podman pull "${image}"

if podman container exists "${name}"; then
  podman rm -f "${name}" >/dev/null
fi

podman run --detach \
  --name "${name}" \
  --network bridge \
  --publish "127.0.0.1:${port}:3212" \
  --restart unless-stopped \
  --env "CHATBOX_API_UPSTREAM=${api_upstream}" \
  --label codespace.kind=service \
  --label "codespace.service=${service}" \
  --label "codespace.image=${image}" \
  "${image}"

echo "Service '${service}' is starting on Host loopback port ${port}."
echo "Forward it with: ssh -N -L ${port}:127.0.0.1:${port} <host>"
