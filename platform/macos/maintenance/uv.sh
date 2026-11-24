#!/usr/bin/env bash
set -euo pipefail

uv_root="$HOME/.local/opt/uv"
test -x "$HOME/.local/bin/uv"
install -d "$uv_root"

env \
  UV_TOOL_DIR="$uv_root/tools" \
  UV_TOOL_BIN_DIR="$uv_root/bin" \
  UV_PYTHON_INSTALL_DIR="$uv_root/python" \
  UV_PYTHON_BIN_DIR="$uv_root/bin" \
  "$HOME/.local/bin/uv" python install --default 3.15.2
