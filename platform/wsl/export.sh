#!/usr/bin/env bash

# WSL imports a flat rootfs, not an OCI image archive.

set -euo pipefail

if (($# > 2)); then
  echo "usage: export.sh [image] [output.wsl]" >&2
  exit 2
fi

image=${1:-ghcr.io/curoky/codespace:workspace-wsl}
out=${2:-codespace.wsl}

cid=$(docker create "${image}")
trap 'docker rm -f "${cid}" >/dev/null 2>&1 || true' EXIT

docker export "${cid}" | gzip >"${out}"

echo "exported ${image} -> ${out}"
echo "install on Windows:  wsl --install --from-file ${out}"
echo "         or:         wsl --import codespace <InstallDir> ${out}"
