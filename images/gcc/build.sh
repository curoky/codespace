#!/usr/bin/env bash

set -xeuo pipefail
cd "$(dirname $0)" || exit 1

# --cache-to=type=inline \
# --cache-from=type=registry,ref=curoky/devspace:${base_image} \
docker build . --network=host --file Dockerfile "${@:2}" \
  --tag curoky/devspace:gcc
# --output type=local,dest=$PWD/temp
