#!/usr/bin/env bats

setup() {
  MACOS_DIR="$(cd "$BATS_TEST_DIRNAME/.." && pwd -P)"
  TEST_ROOT="$(mktemp -d)"
  HOME="$TEST_ROOT/client home"
  TEST_EVENTS="$TEST_ROOT/events"
  UV_CACHE_DIR="$TEST_ROOT/cache"
  export HOME TEST_EVENTS UV_CACHE_DIR
  mkdir -p "$HOME/.local/bin" "$HOME/.local/opt/uv/bin"
  printf '#!/usr/bin/env bash\nexit 0\n' >"$HOME/.local/opt/uv/bin/python3.14"
  cat >"$HOME/.local/bin/uv" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "$UV_TOOL_DIR" == "$HOME/.local/opt/uv/tools" ]]
[[ "$UV_TOOL_BIN_DIR" == "$HOME/.local/opt/uv/bin" ]]
[[ "$UV_PYTHON_INSTALL_DIR" == "$HOME/.local/opt/uv/python" ]]
[[ "$UV_PYTHON_BIN_DIR" == "$HOME/.local/opt/uv/bin" ]]
[[ "$UV_CACHE_DIR" == "${TEST_EVENTS%/*}/cache" ]]
[[ "$1" == tool && "$2" == install && "$4" == --python ]]
[[ "$5" == "$HOME/.local/opt/uv/bin/python3.14" && "$#" == 5 ]]
printf '%s\n' "$3" >>"$TEST_EVENTS"
[[ "$3" != "${TEST_FAIL_PACKAGE:-}" ]] || exit 42
EOF
  chmod 0755 "$HOME/.local/bin/uv" "$HOME/.local/opt/uv/bin/python3.14"
}

teardown() {
  rm -rf "$TEST_ROOT"
}

@test "Python tools install the declared packages under local opt with an explicit interpreter" {
  export UV_TOOL_DIR="$TEST_ROOT/other-tools" UV_TOOL_BIN_DIR="$TEST_ROOT/other-bin"
  export UV_PYTHON_INSTALL_DIR="$TEST_ROOT/other-python" UV_PYTHON_BIN_DIR="$TEST_ROOT/other-python-bin"
  run "$MACOS_DIR/maintenance/python-tools.sh"
  [ "$status" -eq 0 ]
  [ "$(<"$TEST_EVENTS")" = $'copyparty\nlicenseheaders\nnetron\nmitmproxy\ngit-filter-repo' ]
}

@test "Python tools can run repeatedly without cleaning unrelated tools or user data" {
  mkdir -p "$HOME/.local/opt/uv/tools/custom" "$HOME/.local/share/project" "$UV_CACHE_DIR"
  touch "$HOME/.local/opt/uv/tools/custom/keep" "$HOME/.local/share/project/keep" "$UV_CACHE_DIR/keep"
  run "$MACOS_DIR/maintenance/python-tools.sh"
  [ "$status" -eq 0 ]
  run "$MACOS_DIR/maintenance/python-tools.sh"
  [ "$status" -eq 0 ]
  [ "$(wc -l <"$TEST_EVENTS" | tr -d ' ')" = 10 ]
  [ -f "$HOME/.local/opt/uv/tools/custom/keep" ]
  [ -f "$HOME/.local/share/project/keep" ]
  [ -f "$UV_CACHE_DIR/keep" ]
}

@test "Python tools require uv before installing packages" {
  rm "$HOME/.local/bin/uv"
  run "$MACOS_DIR/maintenance/python-tools.sh"
  [ "$status" -eq 1 ]
  [ ! -e "$TEST_EVENTS" ]
}

@test "Python tools do not download a missing runtime" {
  rm "$HOME/.local/opt/uv/bin/python3.14"
  run "$MACOS_DIR/maintenance/python-tools.sh"
  [ "$status" -eq 1 ]
  [ ! -e "$TEST_EVENTS" ]
}

@test "Python tools stop immediately when an installation fails" {
  export TEST_FAIL_PACKAGE=netron
  run "$MACOS_DIR/maintenance/python-tools.sh"
  [ "$status" -eq 42 ]
  [ "$(<"$TEST_EVENTS")" = $'copyparty\nlicenseheaders\nnetron' ]
}
