#!/usr/bin/env bash

set -euo pipefail

podman pull ghcr.io/curoky/devspace:codespace-sidecar

if podman container exists codespace-sidecar; then
  podman rm -f codespace-sidecar >/dev/null
fi

podman run --detach \
  --name codespace-sidecar \
  --network host \
  --restart unless-stopped \
  --env ATUIN_DB_URI=postgres://postgres:[password]@db.hwhoanatmtltozrvpfep.supabase.co:5432/postgres \
  ghcr.io/curoky/devspace:codespace-sidecar

echo "sidecar 'codespace-sidecar' started."
