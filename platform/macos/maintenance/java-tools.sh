#!/usr/bin/env bash
set -euo pipefail

java_root="$HOME/.local/opt/java"
java_tool="$java_root/java-tool"

oras="$HOME/.local/bin/oras"
test -x "$oras"

work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT
"$oras" pull ghcr.io/curoky/codespace:java-tool-darwin-arm64 -o "$work_dir"
tar -xzf "$work_dir/java-tool.tar.gz" -C "$work_dir" java-tool
test -f "$work_dir/java-tool"

rm -rf "$java_tool"
mkdir -p "$java_root/tools/bin"
install -m 0755 "$work_dir/java-tool" "$java_tool"
