#!/usr/bin/env bash
set -xeuo pipefail

if command -v zstd &>/dev/null; then
  compress_type=zstd
else
  compress_type=gzip
fi

curl -L -o /tmp/docker-installer.debian10.sh https://github.com/curoky/devspace/releases/download/v1.0/docker-installer.debian10.${compress_type}.sh
bash /tmp/docker-installer.debian10.sh --target /tmp/docker --noexec # $@

# Usage
# curl -sSL https://github.com/curoky/devspace/raw/master/prepack/docker-offline-installer/debian10/online-installer.sh | bash
