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
	--network bridge \
	--publish 127.0.0.1:8002:8002 \
	--restart unless-stopped \
	--volume /run/podman/podman.sock:/run/podman/podman.sock \
	--env ATUIN_DB_URI=postgresql://postgres.hwhoanatmtltozrvpfep:[YOUR-PASSWORD]@aws-1-ap-southeast-1.pooler.supabase.com:5432/postgres \
	--env ATUIN_HOST=0.0.0.0 \
	--env PODMAN_SOCKET=/run/podman/podman.sock \
	ghcr.io/curoky/devspace:codespace-sidecar

echo "sidecar 'codespace-sidecar' started on http://127.0.0.1:8002."
