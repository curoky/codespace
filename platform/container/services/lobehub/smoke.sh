#!/usr/bin/env bash

set -euo pipefail

if (($# != 0)); then
  echo "Usage: $0" >&2
  exit 2
fi

service="lobehub"
name="codespace-service-${service}"
image="ghcr.io/curoky/codespace:service-${service}"
port="${LOBEHUB_PORT:-3210}"
data="${LOBEHUB_DATA:-${HOME}/codespace/services/${service}}"

mkdir -p -- "${data}"
podman pull "${image}"

if podman container exists "${name}"; then
  podman rm -f "${name}" >/dev/null
fi

podman run --detach \
  --name "${name}" \
  --network bridge \
  --publish "127.0.0.1:${port}:3210" \
  --restart unless-stopped \
  --volume "${data}:/var/lib/codespace/lobehub" \
  --env LOBEHUB_HOST=0.0.0.0 \
  --env APP_URL="http://localhost:${port}" \
  --env OPENAI_PROXY_URL=http://10.88.0.1:8003/v1 \
  --label codespace.kind=service \
  --label "codespace.service=${service}" \
  --label "codespace.image=${image}" \
  "${image}"

echo "Service '${service}' is starting on Host loopback port ${port}."
echo "Forward it with: ssh -N -L ${port}:127.0.0.1:${port} <host>"
