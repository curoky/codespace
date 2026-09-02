#!/usr/bin/env bash
# Start the local Colima Docker runtime with the host development profile.
# Usage: start-colima
# Requires Bash 3.2 or newer and Colima.

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
  command -v colima >/dev/null 2>&1 || {
    printf 'error: colima is required\n' >&2
    return 1
  }

  exec colima start --runtime docker --cpu 8 --memory 16 --disk 100
}

main "$@"
