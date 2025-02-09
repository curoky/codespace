#!/usr/bin/env bash
set -xeuo pipefail

version=${1:-14.2.0}
docker build . \
  --file Dockerfile \
  --network=host \
  --build-arg="GCC_VERSION=$version" \
  --build-arg="ENABLE_2STAGE=false" \
  --tag curoky/devspace:deps-gcc-$version
