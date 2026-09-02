#!/usr/bin/env bash

set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "${script_dir}/../.." && pwd)

base_image=${1:-ghcr.io/curoky/codespace:workspace-ubuntu26.04}
if (($# > 0)); then
  shift
fi
if [[ $base_image != *:* ]]; then
  echo "base image must include a tag: ${base_image}" >&2
  exit 2
fi

image=ghcr.io/curoky/codespace:workspace-wsl

printf 'building %s from %s\n' "$image" "$base_image"
docker build "$repo_root" --network=host --file "$script_dir/Dockerfile" "$@" \
  --build-arg="BASE_IMAGE=${base_image}" \
  --tag "$image" \
  --pull=false
