#!/usr/bin/env bash

set -euo pipefail

podman pull ghcr.io/curoky/devspace:codespace-sidecar

if podman container exists codespace-sidecar; then
	podman rm -f codespace-sidecar >/dev/null
fi

# supercronic runs image-prewarm on a hardcoded schedule: it pulls a hardcoded
# image list and prunes dangling images (see rootfs/etc/supercronic/crontab and
# rootfs/opt/sidecar/image-prewarm.sh).
podman run --detach \
	--name codespace-sidecar \
	--network host \
	--restart unless-stopped \
	--volume /run/podman/podman.sock:/run/podman/podman.sock \
	--env ATUIN_DB_URI=postgres://postgres:[YOUR-PASSWORD]@db.hwhoanatmtltozrvpfep.supabase.co:5432/postgres \
	--env PODMAN_SOCKET=/run/podman/podman.sock \
	ghcr.io/curoky/devspace:codespace-sidecar

echo "sidecar 'codespace-sidecar' started."
