#!/usr/bin/env bash
# Start a rootful Podman machine with the host development profile.
# Usage: start-podman
# Requires the Homebrew Podman managed by this platform.

set -euo pipefail

readonly PODMAN=/opt/homebrew/bin/podman

main() {
  if (($# != 0)); then
    printf 'usage: %s\n' "${0##*/}" >&2
    return 2
  fi

  local machine=podman-machine-default
  local state rootful

  if ! "$PODMAN" machine inspect "$machine" >/dev/null 2>&1; then
    "$PODMAN" machine init \
      --cpus 8 \
      --memory 16384 \
      --disk-size 100 \
      --rootful \
      --now \
      "$machine"
  else
    read -r state rootful < <(
      "$PODMAN" machine inspect --format '{{.State}} {{.Rootful}}' "$machine"
    )
    if [[ "$rootful" != true ]]; then
      if [[ "$state" == running ]]; then
        "$PODMAN" machine stop "$machine"
      fi
      "$PODMAN" machine set --rootful "$machine"
      state=stopped
    fi
    if [[ "$state" != running ]]; then
      "$PODMAN" machine start "$machine"
    fi
  fi

  "$PODMAN" --connection "${machine}-root" info
}

main "$@"
