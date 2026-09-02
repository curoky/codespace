#!/usr/bin/env bash

set -xeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! -d /opt/bm ]]; then
  sudo mkdir -p /opt/bm
  sudo chown x:staff /opt/bm
fi

mkdir -p /opt/bm/bin
curl -fsSL https://raw.githubusercontent.com/curoky/standalone-binaries/refs/heads/master/cmd/binman/install.sh |
  bash -s -- --prefix /opt/bm/bin

/opt/bm/bin/bm sync --prefix /opt/bm "$script_dir/conf/binman.yaml"

ln -sf /opt/bm/bin/bazelisk /opt/bm/bin/bazel
