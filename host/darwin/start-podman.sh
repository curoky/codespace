#!/usr/bin/env bash
set -xeuo pipefail

machine=podman-machine-default

if ! podman machine inspect "$machine" >/dev/null 2>&1; then
  podman machine init \
    --cpus 8 \
    --memory 16384 \
    --disk-size 100 \
    --rootful \
    --now \
    "$machine"
else
  read -r state rootful < <(
    podman machine inspect --format '{{.State}} {{.Rootful}}' "$machine"
  )
  if [[ "$rootful" != true ]]; then
    if [[ "$state" == running ]]; then
      podman machine stop "$machine"
    fi
    podman machine set --rootful "$machine"
    state=stopped
  fi
  if [[ "$state" != running ]]; then
    podman machine start "$machine"
  fi
fi

podman --connection "$machine-root" info
