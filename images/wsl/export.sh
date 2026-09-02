#!/usr/bin/env bash

# Export the WSL flavor image as a flat rootfs tarball importable by WSL.
#
# WSL only understands a single-layer rootfs tar (optionally gzip'd), not an OCI
# layered image, so we `docker export` a container (not `docker save` an image).
# export flattens the filesystem and drops ENTRYPOINT/CMD/ENV, which is exactly
# what we want: all WSL runtime wiring lives in the rootfs (/etc/wsl.conf,
# /opt/wsl/boot.sh) rather than in image metadata.
#
# Renaming the output to *.wsl lets it be installed by double-click or
# `wsl --install --from-file` (WSL >= 2.4.4). It also works with the classic
# `wsl --import <Distro> <InstallDir> devspace.wsl`.

set -euo pipefail
cd "$(dirname "$0")/../.." || exit 1

image=${1:-'ghcr.io/curoky/devspace:codespace-wsl'}
out=${2:-'devspace.wsl'}

cid=$(docker create "${image}")
trap 'docker rm -f "${cid}" >/dev/null 2>&1 || true' EXIT

docker export "${cid}" | gzip >"${out}"

echo "exported ${image} -> ${out}"
echo "install on Windows:  wsl --install --from-file ${out}"
echo "         or:         wsl --import devspace <InstallDir> ${out}"
