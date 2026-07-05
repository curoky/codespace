#!/usr/bin/env bash

# Run the codespace agent container (Podman-out-of-Podman) detached. Any existing
# agent container is stopped and removed first, so this script is safe to re-run.
# The agent is stateless: it only mounts the host podman socket. The workspace
# root is passed through; other service settings are hardcoded in s6 run scripts.

set -euo pipefail

WORKSPACE_ROOT_HOST="${WORKSPACE_ROOT_HOST:-${HOME}/codespace}"

mkdir -p "${WORKSPACE_ROOT_HOST}"

podman pull ghcr.io/curoky/devspace:codespace-agent

if podman container exists codespace-agent; then
  echo "removing existing 'codespace-agent' container..."
  podman rm -f codespace-agent >/dev/null
fi

podman run --detach \
  --name codespace-agent \
  --network host \
  -v /tmp/podmanxd.sock:/tmp/podmanxd.sock \
  -v "${WORKSPACE_ROOT_HOST}:${WORKSPACE_ROOT_HOST}" \
  -e WORKSPACE_ROOT_HOST="${WORKSPACE_ROOT_HOST}" \
  -e ATUIN_DB_URI="${ATUIN_DB_URI:-}" \
  ghcr.io/curoky/devspace:codespace-agent

echo "agent 'codespace-agent' started on port 8001."
