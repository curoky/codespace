#!/usr/bin/env bash
set -xeuo pipefail

podman machine init --cpus 8 --memory 16384 --disk-size 100

podman machine start

podman info
# podman run --rm hello-world
