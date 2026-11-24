#!/usr/bin/env bats

setup() {
  MACOS_DIR="$(cd "$BATS_TEST_DIRNAME/.." && pwd -P)"
  TEST_ROOT="$(mktemp -d)"
  HOME="$TEST_ROOT/client home"
  TMPDIR="$TEST_ROOT/tmp"
  TEST_EVENTS="$TEST_ROOT/events"
  export HOME TMPDIR TEST_ROOT TEST_EVENTS
  mkdir -p "$HOME" "$TMPDIR" "$TEST_ROOT/bin"

  cat >"$TEST_ROOT/bin/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'curl %s\n' "$*" >>"$TEST_EVENTS"
while [[ $# -gt 0 ]]; do
  if [[ $1 == -o ]]; then
    cp "$TEST_ROOT/node.tar.xz" "$2"
    exit 0
  fi
  shift
done
exit 1
EOF
  cat >"$TEST_ROOT/bin/shasum" <<'EOF'
#!/usr/bin/env bash
if [[ ${TEST_BAD_CHECKSUM:-0} == 1 ]]; then
  printf 'invalid\n'
elif [[ $(wc -l <"$TEST_EVENTS") -eq 1 ]]; then
  printf '6239d4cf92d864487ec8cd3615038f7b67e7f58b77b21cd2f09ea9fbd68065fe\n'
else
  printf 'f222f7e85cc1d5a3d84786aa86836ec3d41c4dcdf59a40e4a9d719b6b0ae28af\n'
fi
EOF
  chmod 0755 "$TEST_ROOT/bin/"*
  PATH="$TEST_ROOT/bin:$PATH"
  export PATH
}

teardown() {
  rm -rf "$TEST_ROOT"
}

prepare_node_archive() {
  mkdir -p "$TEST_ROOT/package/node/bin"
  printf '#!/usr/bin/env bash\nexit 0\n' >"$TEST_ROOT/package/node/bin/node"
  chmod 0755 "$TEST_ROOT/package/node/bin/node"
  tar -cJf "$TEST_ROOT/node.tar.xz" -C "$TEST_ROOT/package" node
}

prepare_tool_dependencies() {
  mkdir -p "$HOME/.local/bin" "$HOME/.local/opt/uv/bin" \
    "$HOME/.local/opt/node/nodejs26/bin"
  cat >"$HOME/.local/opt/node/nodejs26/bin/node" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'node %s\n' "$*" >>"$TEST_EVENTS"
printf '%s\n' "$TEST_INSTALLED_VERSION"
EOF
  cat >"$HOME/.local/bin/pnpm" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  cat >"$HOME/.local/bin/uv" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'uv %s\npython %s\nvenv %s\n' "$*" "$UV_PYTHON_INSTALL_DIR" "${VIRTUAL_ENV:-}" >>"$TEST_EVENTS"
mkdir -p "$UV_PROJECT_ENVIRONMENT/bin"
cat >"$UV_PROJECT_ENVIRONMENT/bin/python" <<'PYTHON'
#!/usr/bin/env bash
set -euo pipefail
printf 'python-call %s\n' "$*" >>"$TEST_EVENTS"
root="$HOME/.local/opt/node/tools"
mkdir -p "$root/envs/prettier/node_modules/prettier" "$root/bin"
printf '%s\n' '{"version":"3.9.9"}' >"$root/envs/prettier/node_modules/prettier/package.json"
printf '#!/usr/bin/env bash\nprintf "3.9.9\\n"\n' >"$root/bin/prettier"
chmod 0755 "$root/bin/prettier"
PYTHON
chmod 0755 "$UV_PROJECT_ENVIRONMENT/bin/python"
EOF
  TEST_INSTALLED_VERSION=3.9.9
  export TEST_INSTALLED_VERSION
  printf '#!/usr/bin/env bash\nexit 0\n' >"$HOME/.local/opt/uv/bin/python3.14"
  chmod 0755 "$HOME/.local/bin/"* "$HOME/.local/opt/node/nodejs26/bin/node"
  chmod 0755 "$HOME/.local/opt/uv/bin/python3.14"
}

@test "Node installs both runtimes into the user-local opt layout" {
  prepare_node_archive
  run "$MACOS_DIR/maintenance/node-runtime.sh"
  [ "$status" -eq 0 ]
  [ -x "$HOME/.local/opt/node/nodejs24/bin/node" ]
  [ -x "$HOME/.local/opt/node/nodejs26/bin/node" ]
  [ "$(<"$HOME/.local/opt/node/nodejs24/.codespace-version")" = 24.21.0 ]
  [ "$(<"$HOME/.local/opt/node/nodejs26/.codespace-version")" = 26.10.0 ]
  grep -Fq 'node-v24.21.0-darwin-arm64.tar.xz' "$TEST_EVENTS"
  grep -Fq 'node-v26.10.0-darwin-arm64.tar.xz' "$TEST_EVENTS"

  run "$MACOS_DIR/maintenance/node-runtime.sh"
  [ "$status" -eq 0 ]
  [ "$(wc -l <"$TEST_EVENTS" | tr -d ' ')" = 2 ]
}

@test "Node checksum failure preserves managed and unrelated installations" {
  prepare_node_archive
  mkdir -p "$HOME/.local/opt/node/nodejs24" "$HOME/.local/opt/node/custom"
  touch "$HOME/.local/opt/node/nodejs24/keep" "$HOME/.local/opt/node/custom/keep"
  TEST_BAD_CHECKSUM=1
  export TEST_BAD_CHECKSUM

  run "$MACOS_DIR/maintenance/node-runtime.sh"
  [ "$status" -eq 1 ]
  [[ "$output" == *'checksum mismatch'* ]]
  [ -f "$HOME/.local/opt/node/nodejs24/keep" ]
  [ -f "$HOME/.local/opt/node/custom/keep" ]
  [ ! -e "$HOME/.local/opt/node/nodejs26" ]
}

@test "Node tools isolate Python and install through the shared helper" {
  prepare_tool_dependencies
  VIRTUAL_ENV="$TEST_ROOT/caller-env"
  UV_PROJECT_ENVIRONMENT="$TEST_ROOT/caller-project"
  export VIRTUAL_ENV UV_PROJECT_ENVIRONMENT
  mkdir -p "$HOME/.local/opt/node/tools/envs/custom"
  touch "$HOME/.local/opt/node/tools/envs/custom/keep"

  run "$MACOS_DIR/maintenance/node-tools.sh"
  [ "$status" -eq 0 ]
  local installer="$HOME/.local/opt/node/node-tool"
  [ -x "$installer/node-tool" ]
  [ -x "$installer/.venv/bin/python" ]
  cmp "$installer/node-tool.py" "$MACOS_DIR/../container/workspace/tools/node-tool/node-tool.py"
  grep -Fqx "python $HOME/.local/opt/uv/python" "$TEST_EVENTS"
  grep -Fqx 'venv ' "$TEST_EVENTS"
  grep -Fqx "python-call $installer/node-tool.py install prettier@3.9.9 --node $HOME/.local/opt/node/nodejs26 --pnpm $HOME/.local/bin/pnpm --root $HOME/.local/opt/node/tools" "$TEST_EVENTS"
  [ ! -e "$TEST_ROOT/caller-project" ]
  [ -f "$HOME/.local/opt/node/tools/envs/custom/keep" ]
  [ -x "$HOME/.local/opt/node/tools/bin/prettier" ]

  run "$MACOS_DIR/maintenance/node-tools.sh"
  [ "$status" -eq 0 ]
  [ "$(grep -c '^python-call ' "$TEST_EVENTS")" = 1 ]
  [ -f "$HOME/.local/opt/node/tools/envs/custom/keep" ]
}

@test "Node tools replace only their managed package when its version changes" {
  prepare_tool_dependencies
  run "$MACOS_DIR/maintenance/node-tools.sh"
  [ "$status" -eq 0 ]
  touch "$HOME/.local/opt/node/tools/envs/prettier/stale"
  TEST_INSTALLED_VERSION=0.0.0
  export TEST_INSTALLED_VERSION

  run "$MACOS_DIR/maintenance/node-tools.sh"
  [ "$status" -eq 0 ]
  [ ! -e "$HOME/.local/opt/node/tools/envs/prettier/stale" ]
  [ "$(grep -c '^python-call ' "$TEST_EVENTS")" = 2 ]
}

@test "Node tools fail before copying source when a dependency is missing" {
  for dependency in node pnpm uv python; do
    prepare_tool_dependencies
    case "$dependency" in
      node) rm "$HOME/.local/opt/node/nodejs26/bin/node" ;;
      pnpm) rm "$HOME/.local/bin/pnpm" ;;
      uv) rm "$HOME/.local/bin/uv" ;;
      python) rm "$HOME/.local/opt/uv/bin/python3.14" ;;
    esac
    run "$MACOS_DIR/maintenance/node-tools.sh"
    [ "$status" -eq 1 ]
    [ ! -e "$HOME/.local/opt/node/node-tool" ]
  done
}
