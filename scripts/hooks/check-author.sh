#!/usr/bin/env bash
# Validate Git author identity supplied by a commit hook.
# Usage: check-author.sh [-n NAME] [-e EMAIL]
# Requires Bash 3.2 or newer.

set -euo pipefail

main() {
  if ((BASH_VERSINFO[0] < 3)); then
    printf 'error: Bash 3.2 or newer is required\n' >&2
    return 2
  fi

  local expected_name=""
  local expected_email=""
  local option
  while getopts ':n:e:' option; do
    case "$option" in
      n) expected_name="$OPTARG" ;;
      e) expected_email="$OPTARG" ;;
      :)
        printf 'error: -%s requires a value\n' "$OPTARG" >&2
        return 2
        ;;
      \?)
        printf 'error: unsupported option -%s\n' "$OPTARG" >&2
        return 2
        ;;
    esac
  done
  shift "$((OPTIND - 1))"
  if (($# != 0)); then
    printf 'usage: %s [-n NAME] [-e EMAIL]\n' "${0##*/}" >&2
    return 2
  fi

  if [[ -n "$expected_name" && "$expected_name" != "${GIT_AUTHOR_NAME:-}" ]]; then
    printf "error: expected author name '%s', got '%s'\n" \
      "$expected_name" "${GIT_AUTHOR_NAME:-}" >&2
    return 1
  fi

  if [[ -n "$expected_email" && "$expected_email" != "${GIT_AUTHOR_EMAIL:-}" ]]; then
    printf "error: expected author email '%s', got '%s'\n" \
      "$expected_email" "${GIT_AUTHOR_EMAIL:-}" >&2
    return 1
  fi
}

main "$@"
