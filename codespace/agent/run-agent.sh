#!/usr/bin/env bash

# Reference script to run the codespace agent container (Podman-out-of-Podman).
# The agent is stateless: it only mounts the host podman socket. All flags may
# be overridden via the environment.

set -euo pipefail

IMAGE="${AGENT_IMAGE:-codespace/agent:latest}"
HTTP_PORT="${AGENT_PORT:-8080}"
WORKSPACE_ROOT_HOST="${WORKSPACE_ROOT_HOST:-/var/lib/codespace-workspaces}"
PODMAN_SOCK="${PODMAN_SOCK:-/run/podman/podman.sock}"

exec podman run --rm \
	--name codespace-agent \
	-p "${HTTP_PORT}:8080" \
	-v "${PODMAN_SOCK}:/run/podman/podman.sock" \
	"${IMAGE}" \
	serve \
	--host 0.0.0.0 \
	--port 8080 \
	--workspace-root-host "${WORKSPACE_ROOT_HOST}" \
	--podman-uri "unix:///run/podman/podman.sock"
