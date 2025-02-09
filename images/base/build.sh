#!/usr/bin/env bash

set -xeuo pipefail
cd "$(dirname $0)" || exit 1

base_image=${1:-'debian:10'} #debian:10

# --no-cache \
docker build ../.. --network=host --file Dockerfile "${@:2}" \
  --build-arg="BASE_IMAGE=${base_image}" \
  --tag ghcr.io/curoky/devspace:base-${base_image//:/} --pull=false # --log-level debug --progress plain
