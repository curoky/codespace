#!/usr/bin/env bash

set -xeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Bootstrap the sb client into the prefix, then use it to install everything.
mkdir -p /opt/sb/bin
curl -fsSL https://raw.githubusercontent.com/curoky/standalone-binaries/refs/heads/master/client/install.sh |
  bash -s -- --prefix /opt/sb/bin

# All package sets (linked / unlinked / profiles) and the install prefix are
# declared in the YAML manifest alongside this script. sb sync resolves +
# downloads them in parallel internally, so no shell-level background/wait loop
# is needed. Profiles (s6 / go tools) are aggregated under /opt/sb/profile/<name>/.
/opt/sb/bin/sb sync "$script_dir/sb-pkgs.yaml"

# ln -s -r /opt/sb/bin/clang-format-21 /opt/sb/bin/clang-format
ln -s -r /opt/sb/bin/bazelisk /opt/sb/bin/bazel
rm -rf /opt/sb/store/nettools/bin/hostname

# option
rm -rf /opt/sb/store/cmake/share/cmake*/Help
rm -rf /opt/sb/store/cmake/share/doc
rm -rf /opt/sb/store/vim/share/vim/vim*/doc
rm -rf /opt/sb/store/protobuf*/lib
