#!/usr/bin/env bash

# Run the codespace agent container (Podman-out-of-Podman) detached. Any existing
# agent container is stopped and removed first, so this script is safe to re-run.
# The agent is stateless: it only mounts the host podman socket.

set -euo pipefail

if podman container exists codespace-agent; then
	echo "removing existing 'codespace-agent' container..."
	podman rm -f codespace-agent >/dev/null
fi

podman run --detach \
	--name codespace-agent \
	-p 8080:8080 \
	-v /run/podman/podman.sock:/run/podman/podman.sock \
	ghcr.io/curoky/devspace:codespace-agent \
	serve \
	--host 0.0.0.0 \
	--port 8080 \
	--workspace-root-host /var/lib/codespace-workspaces \
	--podman-uri unix:///run/podman/podman.sock

echo "agent 'codespace-agent' started on port 8080."
