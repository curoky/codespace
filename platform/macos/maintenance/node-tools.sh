#!/usr/bin/env bash
set -euo pipefail

macos_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
node_tool_source="$macos_dir/../container/workspace/tools/node-tool"
node_root="$HOME/.local/opt/node"
node_tool="$node_root/node-tool"
tools_root="$node_root/tools"
environment="$tools_root/envs/prettier"
manifest="$environment/node_modules/prettier/package.json"
version="3.9.9"
installed_version=""

test -x "$node_root/nodejs26/bin/node"
test -x "$HOME/.local/bin/pnpm"
test -x "$HOME/.local/bin/uv"
test -x "$HOME/.local/opt/uv/bin/python3.14"

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

PATH="$HOME/.local/bin:$PATH" UV_PYTHON_INSTALL_DIR="$HOME/.local/opt/uv/python" \
  "$node_tool/node-tool" init

if [[ -f "$manifest" ]]; then
  installed_version="$("$node_root/nodejs26/bin/node" -p 'require(process.argv[1]).version' "$manifest")"
fi
if [[ "$installed_version" == "$version" &&
  -x "$tools_root/bin/prettier" &&
  ! -L "$tools_root/bin/prettier" ]]; then
  exit 0
fi

rm -rf "$environment" "$tools_root/bin/prettier"
PATH="$HOME/.local/bin:$PATH" \
  "$node_tool/node-tool" install "prettier@${version}" \
  --node "$node_root/nodejs26" \
  --pnpm "$HOME/.local/bin/pnpm" \
  --root "$tools_root"
