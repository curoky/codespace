#!/usr/bin/env bash
set -euo pipefail

java_root="$HOME/.local/opt/java"
java_tool="$java_root/java-tool"
cs="$java_root/cs"
cs_version="2.1.27"
cs_sha256="468a4c08483d77f8896b33bcf474e303f716ad43a3f7fb9639cc1112fca9dc1f"
cs_marker="$java_root/.coursier-version"

oras="$HOME/.local/bin/oras"
test -x "$oras"

work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT
"$oras" pull ghcr.io/curoky/codespace:java-tool-darwin-arm64 -o "$work_dir"
tar -xzf "$work_dir/java-tool.tar.gz" -C "$work_dir" java-tool
test -f "$work_dir/java-tool"

if [[ ! -x "$cs" || ! -f "$cs_marker" ]] || [[ "$(<"$cs_marker")" != "$cs_version" ]]; then
  curl -fsSL \
    https://github.com/coursier/coursier/releases/download/v2.1.27/cs-aarch64-apple-darwin.gz \
    -o "$work_dir/cs.gz"
  actual="$(shasum -a 256 "$work_dir/cs.gz" | awk '{print $1}')"
  if [[ "$actual" != "$cs_sha256" ]]; then
    printf 'error: Coursier checksum mismatch\n' >&2
    exit 1
  fi
  gzip -dc "$work_dir/cs.gz" >"$work_dir/cs"
  chmod 0755 "$work_dir/cs"
  "$work_dir/cs" --help >/dev/null
fi

rm -f "$java_tool"
mkdir -p "$java_root"
install -m 0755 "$work_dir/java-tool" "$java_tool"
if [[ -f "$work_dir/cs" ]]; then
  mv "$work_dir/cs" "$cs"
  printf '%s\n' "$cs_version" >"$cs_marker"
fi
