#!/usr/bin/env bash

set -xeuo pipefail
cd "$(dirname "$0")/../.." || exit 1

base_image=${1:-'ghcr.io/curoky/devspace:codespace-ubuntu26.04'}

docker build . --network=host --file images/wsl/Dockerfile "${@:2}" \
  --build-arg="BASE_IMAGE=${base_image}" \
  --tag ghcr.io/curoky/devspace:codespace-wsl \
  --pull=false
