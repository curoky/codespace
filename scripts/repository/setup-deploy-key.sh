#!/usr/bin/env bash
# Create a repository-local deploy key and configure Git to use it.
# Usage: setup-deploy-key.sh
# Requires Bash 3.2 or newer, Git, OpenSSH, and a repository with a .git directory.

set -euo pipefail

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

main() {
  if ((BASH_VERSINFO[0] < 3)); then
    printf 'error: Bash 3.2 or newer is required\n' >&2
    return 2
  fi
  if (($# != 0)); then
    printf 'usage: %s\n' "${0##*/}" >&2
    return 2
  fi

  command -v git >/dev/null 2>&1 || die "git is required"
  command -v ssh-keygen >/dev/null 2>&1 || die "ssh-keygen is required"

  local repo_root key_path public_key_path derived_public_key
  local derived_key_type derived_key_data public_key_type public_key_data
  repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" ||
    die "the current directory is not a Git repository"

  if [[ "$(pwd -P)" != "$(cd "$repo_root" && pwd -P)" ]]; then
    die "run this script from the Git repository root: $repo_root"
  fi
  if [[ ! -d "$repo_root/.git" ]]; then
    die "the repository root does not contain a .git directory"
  fi

  key_path="$repo_root/.git/deploy-key"
  public_key_path="${key_path}.pub"
  if [[ -e "$key_path" || -e "$public_key_path" ]]; then
    if [[ ! -f "$key_path" || ! -f "$public_key_path" ]]; then
      die "found an incomplete deploy key pair at $key_path; resolve it manually before retrying"
    fi

    derived_public_key="$(ssh-keygen -y -P "" -f "$key_path" 2>/dev/null)" ||
      die "the existing private key at $key_path is invalid or passphrase-protected"
    read -r derived_key_type derived_key_data _ <<<"$derived_public_key"
    read -r public_key_type public_key_data _ <"$public_key_path" ||
      die "the existing public key at $public_key_path is invalid"
    if [[ "$derived_key_type" != "$public_key_type" ||
      "$derived_key_data" != "$public_key_data" ]]; then
      die "the existing deploy key files do not form a matching key pair"
    fi
    printf 'Reusing existing deploy key: %s\n' "$key_path"
  else
    ssh-keygen \
      -q \
      -t ed25519 \
      -N "" \
      -C "deploy-key:${repo_root##*/}" \
      -f "$key_path"
    printf 'Generated deploy key: %s\n' "$key_path"
  fi

  chmod 600 "$key_path"
  chmod 644 "$public_key_path"
  git config --local core.sshCommand \
    "ssh -i \"\$(git rev-parse --git-path deploy-key)\" -o IdentitiesOnly=yes"

  printf '\nPublic deploy key (never upload the private key):\n'
  cat "$public_key_path"
  printf '\nThis repository is configured to use the key for SSH operations.\n'
}

main "$@"
