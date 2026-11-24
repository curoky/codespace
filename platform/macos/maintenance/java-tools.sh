#!/usr/bin/env bash
set -euo pipefail

macos_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
java_tool_source="$macos_dir/../container/workspace/tools/java-tool"
java_root="$HOME/.local/opt/java"
java_tool="$java_root/java-tool"

test -x "$java_root/openjdk27/bin/java"
test -x "$HOME/.local/bin/uv"
test -x "$HOME/.local/share/uv/bin/python3.14"

mkdir -p "$java_tool" "$java_root/tools/bin"
install -m 0755 \
  "$java_tool_source/java-tool" \
  "$java_tool_source/java-tool.py" \
  "$java_tool/"
install -m 0644 \
  "$java_tool_source/.python-version" \
  "$java_tool_source/pyproject.toml" \
  "$java_tool_source/uv.lock" \
  "$java_tool/"

PATH="$HOME/.local/bin:$PATH" UV_PYTHON_INSTALL_DIR="$HOME/.local/share/uv/python" \
  "$java_tool/java-tool" init
