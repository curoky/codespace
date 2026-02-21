#!/usr/bin/env bash

set -euo pipefail

if ! podman secret exists atuin_db_uri; then
  echo "missing podman secret 'atuin_db_uri'; create it first: printf '%s' \"\$ATUIN_DB_URI\" | podman secret create atuin_db_uri -" >&2
  exit 1
fi

podman pull ghcr.io/curoky/devspace:codespace-sidecar

if podman container exists codespace-sidecar; then
  podman rm -f codespace-sidecar >/dev/null
fi

# supercronic runs image-prewarm on a hardcoded schedule: it pulls a hardcoded
# image list and prunes dangling images (see rootfs/etc/supercronic/crontab and
# rootfs/opt/sidecar/image-prewarm.sh).
podman run --detach \
  --name codespace-sidecar \
  --network bridge \
  --publish 127.0.0.1:8002:8002 \
  --restart unless-stopped \
  --volume /run/podman/podman.sock:/run/podman/podman.sock \
  --env ATUIN_HOST=0.0.0.0 \
  --env PODMAN_SOCKET=/run/podman/podman.sock \
  --secret atuin_db_uri,type=env,target=ATUIN_DB_URI \
  ghcr.io/curoky/devspace:codespace-sidecar

echo "sidecar 'codespace-sidecar' started on http://127.0.0.1:8002."
