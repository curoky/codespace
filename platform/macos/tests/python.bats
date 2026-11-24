#!/usr/bin/env bats

setup() {
  MACOS_DIR="$(cd "$BATS_TEST_DIRNAME/.." && pwd -P)"
  TEST_ROOT="$(mktemp -d)"
  HOME="$TEST_ROOT/client home"
  TEST_EVENTS="$TEST_ROOT/events"
  export HOME TEST_EVENTS
  mkdir -p "$HOME/.local/bin"
  cat >"$HOME/.local/bin/uv" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'uv %s\ntools %s\ntool-bin %s\npython %s\npython-bin %s\ncache %s\n' \
  "$*" "$UV_TOOL_DIR" "$UV_TOOL_BIN_DIR" "$UV_PYTHON_INSTALL_DIR" \
  "$UV_PYTHON_BIN_DIR" "${UV_CACHE_DIR:-}" >>"$TEST_EVENTS"
mkdir -p "$UV_PYTHON_INSTALL_DIR/runtime/bin" "$UV_PYTHON_BIN_DIR"
printf '#!/usr/bin/env bash\nexit 0\n' >"$UV_PYTHON_INSTALL_DIR/runtime/bin/python3.14"
chmod 0755 "$UV_PYTHON_INSTALL_DIR/runtime/bin/python3.14"
ln -sf "$UV_PYTHON_INSTALL_DIR/runtime/bin/python3.14" "$UV_PYTHON_BIN_DIR/python3.14"
EOF
  chmod 0755 "$HOME/.local/bin/uv"
}

teardown() {
  rm -rf "$TEST_ROOT"
}

@test "Python maintenance configures uv-managed runtime and tool directories under local opt" {
  UV_TOOL_DIR="$TEST_ROOT/caller-tools"
  UV_PYTHON_INSTALL_DIR="$TEST_ROOT/caller-python"
  UV_CACHE_DIR="$TEST_ROOT/cache"
  export UV_TOOL_DIR UV_PYTHON_INSTALL_DIR UV_CACHE_DIR

  run "$MACOS_DIR/maintenance/uv.sh"
  [ "$status" -eq 0 ]
  local root="$HOME/.local/opt/uv"
  [ -x "$root/bin/python3.14" ]
  grep -Fqx 'uv python install 3.14' "$TEST_EVENTS"
  grep -Fqx "tools $root/tools" "$TEST_EVENTS"
  grep -Fqx "tool-bin $root/bin" "$TEST_EVENTS"
  grep -Fqx "python $root/python" "$TEST_EVENTS"
  grep -Fqx "python-bin $root/bin" "$TEST_EVENTS"
  grep -Fqx "cache $TEST_ROOT/cache" "$TEST_EVENTS"
  [ ! -e "$TEST_ROOT/caller-tools" ]
  [ ! -e "$TEST_ROOT/caller-python" ]
}

@test "Python maintenance delegates repeatability to uv without deleting managed or unrelated data" {
  mkdir -p "$HOME/.local/opt/uv/tools/custom" "$HOME/.local/opt/custom-runtime"
  touch "$HOME/.local/opt/uv/tools/custom/keep" "$HOME/.local/opt/custom-runtime/keep"
  run "$MACOS_DIR/maintenance/uv.sh"
  [ "$status" -eq 0 ]
  run "$MACOS_DIR/maintenance/uv.sh"
  [ "$status" -eq 0 ]
  [ "$(grep -Fc 'uv python install 3.14' "$TEST_EVENTS")" = 2 ]
  [ -f "$HOME/.local/opt/uv/tools/custom/keep" ]
  [ -f "$HOME/.local/opt/custom-runtime/keep" ]
}

@test "Python maintenance fails without creating installation directories when uv is missing" {
  rm "$HOME/.local/bin/uv"
  run "$MACOS_DIR/maintenance/uv.sh"
  [ "$status" -eq 1 ]
  [ ! -e "$HOME/.local/opt/uv" ]
}
