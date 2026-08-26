#!/usr/bin/env bash
set -euo pipefail

die() {
  echo "error: $*" >&2
  exit 1
}

if (($# != 0)); then
  echo "usage: ${0##*/}" >&2
  exit 2
fi

repo_root=$(git rev-parse --show-toplevel 2>/dev/null) ||
  die "the current directory is not a Git repository"

if [[ $(pwd -P) != $(cd "$repo_root" && pwd -P) ]]; then
  die "run this script from the Git repository root: $repo_root"
fi

if [[ ! -d $repo_root/.git ]]; then
  die "the repository root does not contain a .git directory"
fi

key_path=$repo_root/.git/deploy-key
public_key_path=${key_path}.pub

if [[ -e $key_path || -e $public_key_path ]]; then
  if [[ ! -f $key_path || ! -f $public_key_path ]]; then
    die "found an incomplete deploy key pair at $key_path; resolve it manually before retrying"
  fi

  derived_public_key=$(ssh-keygen -y -P "" -f "$key_path" 2>/dev/null) ||
    die "the existing private key at $key_path is invalid or passphrase-protected"
  read -r derived_key_type derived_key_data _ <<<"$derived_public_key"
  read -r public_key_type public_key_data _ <"$public_key_path" ||
    die "the existing public key at $public_key_path is invalid"
  if [[ $derived_key_type != "$public_key_type" || $derived_key_data != "$public_key_data" ]]; then
    die "the existing deploy key files do not form a matching key pair"
  fi
  echo "Reusing existing deploy key: $key_path"
else
  ssh-keygen \
    -q \
    -t ed25519 \
    -N "" \
    -C "deploy-key:${repo_root##*/}" \
    -f "$key_path"
  echo "Generated deploy key: $key_path"
fi

chmod 600 "$key_path"
chmod 644 "$public_key_path"

git config --local core.sshCommand \
  'ssh -i "$(git rev-parse --git-path deploy-key)" -o IdentitiesOnly=yes'

echo
echo "Public deploy key (never upload the private key):"
cat "$public_key_path"
echo
echo "This repository is configured to use the key for SSH operations."
