#!/usr/bin/env bash
set -euo pipefail

macos_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
manifest="$macos_dir/../container/workspace/config/python-tools.txt"
uv_root="$HOME/.local/opt/uv"

test -x "$HOME/.local/bin/uv"
test -x "$uv_root/bin/python3.14"

export UV_TOOL_DIR="$uv_root/tools"
export UV_TOOL_BIN_DIR="$uv_root/bin"
export UV_PYTHON_INSTALL_DIR="$uv_root/python"
export UV_PYTHON_BIN_DIR="$uv_root/bin"

while IFS= read -r package; do
  "$HOME/.local/bin/uv" tool install "$package" --python "$uv_root/bin/python3.14"
done <"$manifest"
