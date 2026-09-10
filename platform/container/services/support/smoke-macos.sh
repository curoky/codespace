#!/usr/bin/env bash

set -euo pipefail

if (($# != 0)); then
  echo "Usage: $0" >&2
  exit 2
fi

service="support"
name="codespace-service-${service}"
image="ghcr.io/curoky/codespace:service-${service}"

podman pull "${image}"

if podman container exists "${name}"; then
  podman rm -f "${name}" >/dev/null
fi

podman run --detach \
  --name "${name}" \
  --network bridge \
  --restart unless-stopped \
  --volume /run/podman/podman.sock:/run/podman/podman.sock \
  --env PODMAN_SOCKET=/run/podman/podman.sock \
  --label codespace.kind=service \
  --label "codespace.service=${service}" \
  --label "codespace.image=${image}" \
  "${image}"

echo "Service '${service}' started for image maintenance."
