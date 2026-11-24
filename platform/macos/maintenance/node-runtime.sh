#!/usr/bin/env bash
set -euo pipefail

node_root="$HOME/.local/opt/node"

install_node() {
  local major="$1"
  local version="$2"
  local expected_sha256="$3"
  local destination="$node_root/nodejs${major}"
  local marker="$destination/.codespace-version"

  if [[ -x "$destination/bin/node" && -f "$marker" ]] &&
    [[ "$(<"$marker")" == "$version" ]]; then
    return
  fi

  local work_dir archive actual
  work_dir="$(mktemp -d)"
  archive="$work_dir/node.tar.xz"

  curl -fsSL \
    "https://nodejs.org/dist/v${version}/node-v${version}-darwin-arm64.tar.xz" \
    -o "$archive"
  actual="$(shasum -a 256 "$archive" | awk '{print $1}')"
  if [[ "$actual" != "$expected_sha256" ]]; then
    rm -rf "$work_dir"
    printf 'error: Node.js %s checksum mismatch\n' "$version" >&2
    return 1
  fi

  rm -rf "${destination}.installing"
  mkdir -p "${destination}.installing"
  tar -xf "$archive" --strip-components=1 -C "${destination}.installing"
  printf '%s\n' "$version" >"${destination}.installing/.codespace-version"
  rm -rf "$destination"
  mv "${destination}.installing" "$destination"
  rm -rf "$work_dir"
}

install_node \
  24 \
  24.21.0 \
  6239d4cf92d864487ec8cd3615038f7b67e7f58b77b21cd2f09ea9fbd68065fe
install_node \
  26 \
  26.10.0 \
  f222f7e85cc1d5a3d84786aa86836ec3d41c4dcdf59a40e4a9d719b6b0ae28af
