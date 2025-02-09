#!/usr/bin/env bash
set -xeuo pipefail

version=${1:-3.13.7}
docker build . \
  --file Dockerfile \
  --network=host \
  --build-arg="PYTHON_VERSION=${version}" \
  --tag curoky/devspace:deps-python-${version}
