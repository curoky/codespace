#!/usr/bin/env bash
# Start a rootful Podman machine with the host development profile.
# Usage: start-podman
# Requires Bash 3.2 or newer and Podman.

set -euo pipefail

main() {
  if ((BASH_VERSINFO[0] < 3)); then
    printf 'error: Bash 3.2 or newer is required\n' >&2
    return 2
  fi
  if (($# != 0)); then
    printf 'usage: %s\n' "${0##*/}" >&2
    return 2
  fi
  command -v podman >/dev/null 2>&1 || {
    printf 'error: podman is required\n' >&2
    return 1
  }

  local machine=podman-machine-default
  local state rootful

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

  podman --connection "${machine}-root" info
}

main "$@"
