#!/usr/bin/env bash

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../../.."

docker build . --network=host --file images/deployments/sidecar/Dockerfile \
  --tag ghcr.io/curoky/devspace:codespace-sidecar
