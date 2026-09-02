#!/usr/bin/env bash
# Add or update Apache-2.0 headers in the current Git repository.
# Usage: add-license.sh [PATH]
# Requires Bash 3.2 or newer, Git, and licenseheaders.

set -euo pipefail

main() {
  if ((BASH_VERSINFO[0] < 3)); then
    printf 'error: Bash 3.2 or newer is required\n' >&2
    return 2
  fi
  if (($# > 1)); then
    printf 'usage: %s [PATH]\n' "${0##*/}" >&2
    return 2
  fi

  command -v git >/dev/null 2>&1 || {
    printf 'error: git is required\n' >&2
    return 1
  }
  command -v licenseheaders >/dev/null 2>&1 || {
    printf 'error: licenseheaders is required\n' >&2
    return 1
  }

  local repo_root script_dir target remote_url project_url
  local first_year current_year owner_name owner_email
  repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || {
    printf 'error: the current directory is not a Git repository\n' >&2
    return 1
  }
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
  target="${1:-.}"

  remote_url="$(git -C "$repo_root" remote get-url origin)"
  project_url="$(printf '%s\n' "$remote_url" |
    sed -e 's|^git@github.com:|https://github.com/|' -e 's|\.git$||')"
  first_year="$(git -C "$repo_root" log --reverse --date=format:%Y --format=%ad |
    sed -n '1p')"
  current_year="$(date +%Y)"
  owner_name="$(git -C "$repo_root" config user.name)"
  owner_email="$(git -C "$repo_root" config user.email)"

  if [[ -z "$first_year" || -z "$owner_name" || -z "$owner_email" ]]; then
    printf 'error: commit history and Git user name/email are required\n' >&2
    return 1
  fi

  licenseheaders \
    --tmpl="$script_dir/license/apache-2.tmpl" \
    --owner="$owner_name($owner_email)" \
    --projname="${repo_root##*/}" \
    --projurl="$project_url" \
    --settings="$script_dir/license/settings.json" \
    --exclude '*.yaml' '*.md' '*.gzip.sh' '*.zstd.sh' \
    --dir "$target" \
    --years="$first_year-$current_year"
}

main "$@"
