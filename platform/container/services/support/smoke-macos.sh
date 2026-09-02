#!/usr/bin/env bash

set -euo pipefail

if (($# != 0)); then
  echo "Usage: $0" >&2
  exit 2
fi

service="support"
name="codespace-service-${service}"
image="ghcr.io/curoky/codespace:service-${service}"

if ! podman secret exists atuin_db_uri; then
  echo "missing podman secret 'atuin_db_uri'; create it first: printf '%s' \"\$ATUIN_DB_URI\" | podman secret create atuin_db_uri -" >&2
  exit 1
fi

podman pull "${image}"

if podman container exists "${name}"; then
  podman rm -f "${name}" >/dev/null
fi

podman run --detach \
  --name "${name}" \
  --network bridge \
  --publish 127.0.0.1:8002:8002 \
  --restart unless-stopped \
  --volume /run/podman/podman.sock:/run/podman/podman.sock \
  --env ATUIN_HOST=0.0.0.0 \
  --env PODMAN_SOCKET=/run/podman/podman.sock \
  --secret atuin_db_uri,type=env,target=ATUIN_DB_URI \
  --label codespace.kind=service \
  --label "codespace.service=${service}" \
  --label "codespace.image=${image}" \
  "${image}"

echo "Service '${service}' started on http://127.0.0.1:8002."
