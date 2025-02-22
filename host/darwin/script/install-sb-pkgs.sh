#!/usr/bin/env bash

set -xeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! -d /opt/sb ]]; then
  sudo mkdir -p /opt/sb
  sudo chown x:staff /opt/sb
fi

# Bootstrap the sb client into the prefix, then use it to install everything.
mkdir -p /opt/sb/bin
curl -fsSL https://raw.githubusercontent.com/curoky/standalone-binaries/refs/heads/master/client/install.sh |
  bash -s -- --prefix /opt/sb/bin

# All package sets (linked / unlinked) and the install prefix / arch are
# declared in the YAML manifest alongside this script. sb sync resolves +
# downloads them in parallel internally, so no shell-level background/wait loop
# is needed. nodejs-slim26 / perl are installed unlinked (binaries not exposed).
/opt/sb/bin/sb sync "$script_dir/sb-pkgs.yaml"

ln -sf /opt/sb/bin/bazelisk /opt/sb/bin/bazel
