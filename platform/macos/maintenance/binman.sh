#!/usr/bin/env bash
set -euo pipefail

macos_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
prefix="$HOME/.local"
installer="/tmp/binman-install.sh"

install -d "$prefix"
curl -fsSL \
  https://raw.githubusercontent.com/curoky/standalone-binaries/refs/heads/master/cmd/binman/install.sh \
  -o "$installer"
/bin/bash "$installer" --prefix "$prefix"

"$prefix/bin/bm" --prefix "$prefix" install --file "$macos_dir/binman.yaml"
ln -sfn bazelisk "$prefix/bin/bazel"
