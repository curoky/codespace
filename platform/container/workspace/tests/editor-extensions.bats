#!/usr/bin/env bats

setup() {
  WORKSPACE_DIR="$(cd "$BATS_TEST_DIRNAME/.." && pwd -P)"
  TEST_ROOT="$(mktemp -d "$BATS_TEST_TMPDIR/extensions.XXXXXX")"
  TEMPLATE="$TEST_ROOT/template"
  CACHE="$TEST_ROOT/cache"
  export TEST_ROOT
  mkdir -p "$TEST_ROOT/bin"
  printf 'publisher.example\n' >"$TEST_ROOT/extensions.txt"

  cat >"$TEST_ROOT/bin/curl" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  cat >"$TEST_ROOT/bin/tar" <<'EOF'
#!/usr/bin/env bash
set -eu
while [[ "$1" != -C ]]; do shift; done
mkdir -p "$2/bin"
cp "$TEST_ROOT/code-server" "$2/bin/code-server"
EOF
  cat >"$TEST_ROOT/code-server" <<'EOF'
#!/usr/bin/env bash
set -eu
[[ ${FAIL_INSTALL:-false} == false ]] || exit 7
target="$2"
mkdir -p "$target/publisher.example-1.0"
printf 'extension payload' >"$target/publisher.example-1.0/package.json"
printf '[{"identifier":{"id":"publisher.example"},"version":"1.0","metadata":{"isBuiltin":false},"location":{"path":"%s/publisher.example-1.0","scheme":"file"}}]\n' "$target" >"$target/extensions.json"
EOF
  chmod +x "$TEST_ROOT/bin/"* "$TEST_ROOT/code-server"
  export PATH="$TEST_ROOT/bin:$PATH"
  for server in .vscode-server .trae-server .trae-cn-server; do
    mkdir -p "$CACHE/$server/extensions"
  done
  sed -e "s#/opt/codespace/share/editor-extensions#$TEMPLATE#g" \
    -e "s#/cache/#$CACHE/#g" \
    "$WORKSPACE_DIR/rootfs/opt/codespace/bin/seed-editor-extensions" >"$TEST_ROOT/seed"
}

teardown() {
  rm -rf "$TEST_ROOT"
}

build_template() {
  bash "$WORKSPACE_DIR/scripts/install-editor-extensions.sh" "$TEST_ROOT/extensions.txt" "$TEMPLATE"
}

@test "build prepares every IDE manifest and runtime copies it verbatim" {
  run build_template
  [[ "$status" -eq 0 ]]
  [[ ! -e "$TEMPLATE/extensions/extensions.json" ]]

  run bash "$TEST_ROOT/seed"
  [[ "$status" -eq 0 ]]
  for server in .vscode-server .trae-server .trae-cn-server; do
    target="$CACHE/$server/extensions"
    cmp "$TEMPLATE/$server.json" "$target/extensions.json"
    [[ "$(jq -r '.[0].location.path' "$target/extensions.json")" == "/home/x/$server/extensions/publisher.example-1.0" ]]
    [[ "$(jq -r '.[0].relativeLocation' "$target/extensions.json")" == publisher.example-1.0 ]]
    jq -e '.[0] | .version == "1.0" and .metadata.isBuiltin == false' "$target/extensions.json"
    [[ "$(cat "$target/publisher.example-1.0/package.json")" == "extension payload" ]]
  done
}

@test "recreated containers preserve user manifests and removed extensions" {
  build_template
  bash "$TEST_ROOT/seed"
  printf '[]\n' >"$CACHE/.vscode-server/extensions/extensions.json"
  rm -rf "$CACHE/.vscode-server/extensions/publisher.example-1.0"
  rm -rf "$TEMPLATE"

  run bash "$TEST_ROOT/seed"
  [[ "$status" -eq 0 ]]
  [[ "$(cat "$CACHE/.vscode-server/extensions/extensions.json")" == "[]" ]]
  [[ ! -e "$CACHE/.vscode-server/extensions/publisher.example-1.0" ]]
}

@test "copy failure does not publish a manifest and can be retried" {
  build_template
  mv "$TEMPLATE/extensions" "$TEST_ROOT/payload"

  run bash "$TEST_ROOT/seed"
  [[ "$status" -ne 0 ]]
  [[ ! -e "$CACHE/.vscode-server/extensions/extensions.json" ]]

  mv "$TEST_ROOT/payload" "$TEMPLATE/extensions"
  run bash "$TEST_ROOT/seed"
  [[ "$status" -eq 0 ]]
  cmp "$TEMPLATE/.vscode-server.json" "$CACHE/.vscode-server/extensions/extensions.json"
}

@test "extension installation failure fails the build instead of publishing a partial template" {
  export FAIL_INSTALL=true

  run build_template

  [[ "$status" -eq 7 ]]
  [[ ! -e "$TEMPLATE/.vscode-server.json" ]]
}
