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
  24.22.3 \
  1d64136c8a43d648d1b3bad10797a4c995b1ca032d2bde8799de43b37f058fe5
install_node \
  26 \
  26.13.1 \
  af6202f5370a3a5209e85dc543758dfd9f44c8726626a236730cd603a67a8559
