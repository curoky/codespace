#!/usr/bin/env bash

set -xeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! -d /opt/sb ]]; then
  sudo mkdir -p /opt/sb
  sudo chown x:staff /opt/sb
fi

mkdir -p /opt/sb/bin
curl -fsSL https://raw.githubusercontent.com/curoky/standalone-binaries/refs/heads/master/cmd/binman/install.sh |
  bash -s -- --prefix /opt/sb/bin

/opt/sb/bin/bm sync --prefix /opt/sb "$script_dir/conf/binman.yaml"

ln -sf /opt/sb/bin/bazelisk /opt/sb/bin/bazel
