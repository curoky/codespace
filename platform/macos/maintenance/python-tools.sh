#!/usr/bin/env bash
set -euo pipefail

uv_root="$HOME/.local/opt/uv"

test -x "$HOME/.local/bin/uv"

export UV_TOOL_DIR="$uv_root/tools"
export UV_TOOL_BIN_DIR="$uv_root/bin"
export UV_PYTHON_INSTALL_DIR="$uv_root/python"
export UV_PYTHON_BIN_DIR="$uv_root/bin"

test -x "$UV_PYTHON_BIN_DIR/python3.15"

"$HOME/.local/bin/uv" tool install copyparty --python "$UV_PYTHON_BIN_DIR/python3.15" --upgrade
"$HOME/.local/bin/uv" tool install licenseheaders --python "$UV_PYTHON_BIN_DIR/python3.15" --upgrade
"$HOME/.local/bin/uv" tool install netron --python "$UV_PYTHON_BIN_DIR/python3.15" --upgrade
"$HOME/.local/bin/uv" tool install mitmproxy --python "$UV_PYTHON_BIN_DIR/python3.15" --upgrade
"$HOME/.local/bin/uv" tool install git-filter-repo --python "$UV_PYTHON_BIN_DIR/python3.15" --upgrade
