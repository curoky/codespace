#!/usr/bin/env bash
set -euo pipefail

macos_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
node_tool_source="$macos_dir/../container/workspace/tools/node-tool"
node_root="$HOME/.local/share/node"
node_tool="$node_root/node-tool"
tools_root="$node_root/tools"
environment="$tools_root/envs/prettier"
manifest="$environment/node_modules/prettier/package.json"
version="3.9.9"
installed_version=""

mkdir -p "$node_tool"
install -m 0755 \
  "$node_tool_source/node-tool" \
  "$node_tool_source/node-tool.py" \
  "$node_tool/"
install -m 0644 \
  "$node_tool_source/.python-version" \
  "$node_tool_source/pyproject.toml" \
  "$node_tool_source/uv.lock" \
  "$node_tool/"

PATH="$HOME/.local/bin:$PATH" \
  "$node_tool/node-tool" init \
  --uv "$HOME/.local/bin/uv" \
  --python-install-dir "$HOME/.local/share/uv/python"

if [[ -f "$manifest" ]]; then
  installed_version="$(/usr/bin/plutil -extract version raw -o - "$manifest")"
fi
if [[ "$installed_version" == "$version" &&
  -x "$tools_root/bin/prettier" &&
  ! -L "$tools_root/bin/prettier" ]]; then
  exit 0
fi

rm -rf "$environment" "$tools_root/bin/prettier"
PATH="$HOME/.local/bin:$PATH" \
  "$node_tool/node-tool" install "prettier@${version}" \
  --node "$node_root/nodejs24" \
  --pnpm "$HOME/.local/bin/pnpm" \
  --root "$tools_root"
