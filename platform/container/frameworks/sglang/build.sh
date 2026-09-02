#!/usr/bin/env bash

# Build an SGLang framework image. Pass a combo name to select a Dockerfile.

set -euo pipefail

if (($# > 1)); then
  echo "Usage: $0 [combo]" >&2
  exit 2
fi

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "${script_dir}/../../../.." && pwd)
combo="${1:-sglang0.5.18-cu12.9.1-cudnn9-gcc12-py3.12}"

if [[ ! "${combo}" =~ ^[a-z0-9][a-z0-9.-]*$ ]]; then
  echo "invalid combo: ${combo}" >&2
  exit 2
fi

dockerfile="${script_dir}/${combo}.Dockerfile"
if [[ ! -f "${dockerfile}" ]]; then
  echo "unknown combo: ${combo}" >&2
  exit 2
fi

image="ghcr.io/curoky/codespace:framework-${combo}"

printf 'building %s from %s\n' "${image}" "${combo}"
docker build "${repo_root}" --network=host \
  --file "${dockerfile}" \
  --tag "${image}"
