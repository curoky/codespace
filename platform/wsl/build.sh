#!/usr/bin/env bash

set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "${script_dir}/../.." && pwd)

image=ghcr.io/curoky/codespace:workspace-wsl

printf 'building %s\n' "$image"
docker build "$repo_root" --network=host --file "$script_dir/Dockerfile" "$@" \
  --tag "$image" \
  --pull=false
