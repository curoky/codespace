#!/usr/bin/env bash

set -xeuo pipefail
cd "$(dirname "$0")/../../.." || exit 1

base_image=${1:-'debian:13'}

# --no-cache \
docker build . --network=host --file codespace/images/dev/Dockerfile "${@:2}" \
  --build-arg="BASE_IMAGE=${base_image}" \
  --tag ghcr.io/curoky/devspace:codespace-${base_image//:/} \
  --pull=false # --log-level debug --progress plain
