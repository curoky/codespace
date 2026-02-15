#!/usr/bin/env bash

# Pull a fixed image list and prune dangling images on the host so development
# containers start from a warm local cache. Invoked by supercronic per the
# schedule in /etc/supercronic/crontab; each subcommand runs once and exits.
#
# Usage: image-prewarm.sh {pull|prune}
#   pull   pull every image in the hardcoded PREWARM_IMAGES list
#   prune  prune dangling (untagged) images
#
# The image list is hardcoded below (PREWARM_IMAGES); edit it here to change
# what gets warmed. The pull/prune schedule lives in /etc/supercronic/crontab.
# The remaining knobs come from the container environment (dumped by s6 into
# /run/s6/container_environment and loaded by the execline run script):
#
#   PODMAN_SOCKET            host rootful Podman socket bind-mounted into the
#                            sidecar (default /run/podman/podman.sock)
#   PREWARM_TIMEOUT_SECONDS  per-request curl timeout in seconds (default 900)
#
# The sidecar only pulls images and prunes dangling layers; it never removes
# tagged images, so images referenced by managed containers are always safe.
# Only the host native platform is warmed.

set -uo pipefail

# Images pre-pulled every cycle. Edit this list to change what gets warmed.
PREWARM_IMAGES=(
  ghcr.io/curoky/devspace:codespace-debian13
)

socket="${PODMAN_SOCKET:-/run/podman/podman.sock}"
timeout_seconds="${PREWARM_TIMEOUT_SECONDS:-900}"

# Any semver in [3.1.0, server] selects the libpod routes; v4.0.0 works on
# Podman 4.x and 5.x hosts alike.
api_base="http://d/v4.0.0/libpod"

log() {
  echo "$(date -Is) image-prewarm: $*"
}

curl_api() {
  curl --silent --show-error --max-time "${timeout_seconds}" --unix-socket "${socket}" "$@"
}

pull_one() {
  local image="$1" output
  if ! output=$(curl_api -G -X POST \
    --data-urlencode "reference=${image}" \
    "${api_base}/images/pull" 2>&1); then
    log "pull ${image} failed: ${output}"
    return 1
  fi
  if grep -q '"error"' <<<"${output}"; then
    log "pull ${image} reported an error: ${output}"
    return 1
  fi
  log "pulled ${image}"
}

pull_all() {
  if [[ "${#PREWARM_IMAGES[@]}" -eq 0 ]]; then
    log "PREWARM_IMAGES is empty; nothing to pull"
    return 0
  fi
  for image in "${PREWARM_IMAGES[@]}"; do
    pull_one "${image}" || true
  done
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

case "${1:-}" in
  pull) pull_all ;;
  prune) prune_dangling || true ;;
  *)
    log "usage: ${0##*/} {pull|prune}"
    exit 2
    ;;
esac
