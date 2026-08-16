#!/usr/bin/env bash

set -uo pipefail

readonly socket=/run/podman/podman.sock
readonly timeout_seconds=900

# The v4 compatibility route works with supported Podman 4.x and 5.x Hosts.
api_base="http://d/v4.0.0/libpod"

log() {
  echo "$(date -Is) prune-images: $*"
}

curl_api() {
  curl --silent --show-error --max-time "${timeout_seconds}" --unix-socket "${socket}" "$@"
}

prune_dangling() {
  local output
  if ! output=$(curl_api -X POST "${api_base}/images/prune" 2>&1); then
    log "prune dangling images failed: ${output}"
    return 1
  fi
  log "pruned dangling images"
}

prune_dangling || true
