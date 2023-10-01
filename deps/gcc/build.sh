#!/usr/bin/env bash
set -xeuo pipefail

docker buildx build . \
  --file Dockerfile \
  --network=host \
  --build-arg="GCC_VERSION=14.2.0" \
  --tag curoky/devspace:stage-gcc-14.2.0
