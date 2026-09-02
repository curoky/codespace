#!/usr/bin/env bash

set -euo pipefail

if (($# != 0)); then
  echo "Usage: $0" >&2
  exit 2
fi

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "${script_dir}/../../../.." && pwd)
image="ghcr.io/curoky/codespace:service-support"

printf 'building %s\n' "${image}"
docker build "${repo_root}" --network=host \
  --file "${script_dir}/Dockerfile" \
  --tag "${image}"
