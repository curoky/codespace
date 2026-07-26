#!/usr/bin/env bash

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

docker build . --network=host --file codespace/sidecar/Dockerfile \
  --tag ghcr.io/curoky/devspace:codespace-sidecar
