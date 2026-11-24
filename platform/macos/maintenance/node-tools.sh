#!/usr/bin/env bash
set -euo pipefail

node_root="$HOME/.local/opt/node"
node_tool="$node_root/node-tool"
tools_root="$node_root/tools"

test -x "$node_root/nodejs26/bin/node"
test -x "$HOME/.local/bin/pnpm"
oras="$HOME/.local/bin/oras"
test -x "$oras"

work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT
"$oras" pull ghcr.io/curoky/codespace:node-tool-darwin-arm64 -o "$work_dir"
tar -xzf "$work_dir/node-tool.tar.gz" -C "$work_dir" node-tool
test -f "$work_dir/node-tool"

rm -rf "$node_tool" "$tools_root"
mkdir -p "$node_root"
install -m 0755 "$work_dir/node-tool" "$node_tool"

export PATH="$node_root:$HOME/.local/bin:$PATH"
node-tool install defuddle@0.19.4
node-tool install markdownlint-cli2@0.23.3
node-tool install prettier@3.9.9
