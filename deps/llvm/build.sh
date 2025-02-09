#!/usr/bin/env bash
set -xeuo pipefail

version=${1:-21.1.0}
docker build . \
  --file Dockerfile \
  --network=host \
  --build-arg="LLVM_VERSION=$version" \
  --build-arg="ENABLE_2STAGE=true" \
  --tag curoky/devspace:deps-llvm-$version
