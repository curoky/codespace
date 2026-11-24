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
exit 0
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
[[ "$3" != "${TEST_FAIL_PACKAGE:-}" ]] || exit 42
package="${3%@*}"
version="${3##*@}"
root="$HOME/.local/opt/node/tools"
mkdir -p "$root/envs/$package/node_modules/$package" "$root/bin"
printf '{"name":"%s","version":"%s","bin":{"%s":"cli.js"}}\n' "$package" "$version" "$package" \
  >"$root/envs/$package/node_modules/$package/package.json"
printf '#!/usr/bin/env bash\nexit 0\n' >"$root/bin/$package"
chmod 0755 "$root/bin/$package"
PYTHON
chmod 0755 "$UV_PROJECT_ENVIRONMENT/bin/python"
EOF
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

@test "Node tools rebuild their managed directories and install through the shared helper" {
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
  for package in defuddle@0.19.4 markdownlint-cli2@0.23.3 prettier@3.9.9; do
    grep -Fqx "python-call $installer/node-tool.py install $package --node $HOME/.local/opt/node/nodejs26 --pnpm $HOME/.local/bin/pnpm --root $HOME/.local/opt/node/tools" "$TEST_EVENTS"
    [ -x "$HOME/.local/opt/node/tools/bin/${package%@*}" ]
  done
  [ ! -e "$TEST_ROOT/caller-project" ]
  [ ! -e "$HOME/.local/opt/node/tools/envs/custom" ]
  [ -x "$HOME/.local/opt/node/tools/bin/prettier" ]

  run "$MACOS_DIR/maintenance/node-tools.sh"
  [ "$status" -eq 0 ]
  [ "$(grep -c '^python-call ' "$TEST_EVENTS")" = 6 ]
  [ ! -e "$HOME/.local/opt/node/tools/envs/custom" ]
}

@test "Node tools rebuild their entire installation without touching other runtimes or user caches" {
  prepare_tool_dependencies
  run "$MACOS_DIR/maintenance/node-tools.sh"
  [ "$status" -eq 0 ]
  local root="$HOME/.local/opt/node/tools"
  for package in defuddle markdownlint-cli2 prettier; do
    touch "$root/envs/$package/stale"
  done
  mkdir -p "$root/envs/custom" "$root/store" "$HOME/.cache/npm" "$HOME/.local/opt/node/node-tool"
  touch "$root/envs/custom/keep" "$root/store/keep" "$HOME/.cache/npm/keep"
  touch "$HOME/.local/opt/node/node-tool/stale"

  run "$MACOS_DIR/maintenance/node-tools.sh"
  [ "$status" -eq 0 ]
  for package in defuddle markdownlint-cli2 prettier; do
    [ ! -e "$root/envs/$package/stale" ]
  done
  [ ! -e "$root/envs/custom" ]
  [ ! -e "$root/store/keep" ]
  [ ! -e "$HOME/.local/opt/node/node-tool/stale" ]
  [ -x "$HOME/.local/opt/node/nodejs26/bin/node" ]
  [ -f "$HOME/.cache/npm/keep" ]
  [ "$(grep -c '^python-call ' "$TEST_EVENTS")" = 6 ]
}

@test "Node tools replace partial installations without reading package metadata" {
  prepare_tool_dependencies
  run "$MACOS_DIR/maintenance/node-tools.sh"
  [ "$status" -eq 0 ]
  rm "$HOME/.local/opt/node/tools/envs/defuddle/node_modules/defuddle/package.json"
  rm "$HOME/.local/opt/node/tools/bin/prettier"
  run "$MACOS_DIR/maintenance/node-tools.sh"
  [ "$status" -eq 0 ]
  [ -x "$HOME/.local/opt/node/tools/bin/prettier" ]
  [ -f "$HOME/.local/opt/node/tools/envs/defuddle/node_modules/defuddle/package.json" ]
  [ "$(grep -c '^python-call ' "$TEST_EVENTS")" = 6 ]
}

@test "Node tools stop immediately when a package installation fails" {
  prepare_tool_dependencies
  export TEST_FAIL_PACKAGE=markdownlint-cli2@0.23.3
  run "$MACOS_DIR/maintenance/node-tools.sh"
  [ "$status" -eq 42 ]
  [ -x "$HOME/.local/opt/node/tools/bin/defuddle" ]
  [ ! -e "$HOME/.local/opt/node/tools/envs/prettier" ]
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
