#!/usr/bin/env bash
set -euo pipefail

macos_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
node_tool_source="$macos_dir/../container/workspace/tools/node-tool"
node_root="$HOME/.local/opt/node"
node_tool="$node_root/node-tool"
tools_root="$node_root/tools"

test -x "$node_root/nodejs26/bin/node"
test -x "$HOME/.local/bin/pnpm"
test -x "$HOME/.local/bin/uv"
test -x "$HOME/.local/opt/uv/bin/python3.14"

rm -rf "$node_tool" "$tools_root"
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

export PATH="$HOME/.local/bin:$PATH"
UV_PYTHON_INSTALL_DIR="$HOME/.local/opt/uv/python" \
  "$node_tool/node-tool" init

"$node_tool/node-tool" install defuddle@0.19.4 \
  --node "$node_root/nodejs26" --pnpm "$HOME/.local/bin/pnpm" --root "$tools_root"
"$node_tool/node-tool" install markdownlint-cli2@0.23.3 \
  --node "$node_root/nodejs26" --pnpm "$HOME/.local/bin/pnpm" --root "$tools_root"
"$node_tool/node-tool" install prettier@3.9.9 \
  --node "$node_root/nodejs26" --pnpm "$HOME/.local/bin/pnpm" --root "$tools_root"
