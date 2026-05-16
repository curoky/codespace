#!/usr/bin/env bash

# Prune dangling (untagged) images on the host so the local cache does not grow
# without bound. Runs one cycle and exits.
#
# Usage: image-prune.sh
#
# Runtime inputs:
#
#   PODMAN_SOCKET            host rootful Podman socket bind-mounted into the
#                            support service (default /run/podman/podman.sock)
#   PREWARM_TIMEOUT_SECONDS  per-request curl timeout in seconds (default 900)
#
# The support service only prunes dangling layers; it never removes tagged
# images, so images referenced by managed containers are always safe.

set -uo pipefail

socket="${PODMAN_SOCKET:-/run/podman/podman.sock}"
timeout_seconds="${PREWARM_TIMEOUT_SECONDS:-900}"

# Any semver in [3.1.0, server] selects the libpod routes; v4.0.0 works on
# Podman 4.x and 5.x hosts alike.
api_base="http://d/v4.0.0/libpod"

log() {
  echo "$(date -Is) prune-images: $*"
}

curl_api() {
  curl --silent --show-error --max-time "${timeout_seconds}" --unix-socket "${socket}" "$@"
}

prune_dangling() {
  local output
  # No filters and no all=true prunes only dangling (untagged) images.
  if ! output=$(curl_api -X POST "${api_base}/images/prune" 2>&1); then
    log "prune dangling images failed: ${output}"
    return 1
  fi
  log "pruned dangling images"
}

prune_dangling || true
