#!/usr/bin/env bash

set -uo pipefail

readonly -a PREWARM_IMAGES=(
  ghcr.io/curoky/codespace:workspace-debian13
)

readonly socket=/run/podman/podman.sock
readonly timeout_seconds=900

api_base="http://d/v4.0.0/libpod"

log() {
  echo "$(date -Is) pull-images: $*"
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

pull_all
