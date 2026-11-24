#!/usr/bin/env bats

setup() {
  MACOS_DIR="$(cd "$BATS_TEST_DIRNAME/.." && pwd -P)"
  TEST_ROOT="$(mktemp -d)"
  HOME="$TEST_ROOT/client home"
  TMPDIR="$TEST_ROOT/tmp"
  TEST_ARCHIVE="$TEST_ROOT/go.tar.gz"
  TEST_EVENTS="$TEST_ROOT/events"
  TEST_SHA256="$(sed -n 's/^expected_sha256="\(.*\)"$/\1/p' "$MACOS_DIR/maintenance/go.sh")"
  export HOME TMPDIR TEST_ROOT TEST_ARCHIVE TEST_EVENTS TEST_SHA256
  mkdir -p "$HOME" "$TMPDIR" "$TEST_ROOT/bin" "$TEST_ROOT/package/go/bin"
  printf '#!/usr/bin/env bash\nexit 0\n' >"$TEST_ROOT/package/go/bin/go"
  cp "$TEST_ROOT/package/go/bin/go" "$TEST_ROOT/package/go/bin/gofmt"
  chmod 0755 "$TEST_ROOT/package/go/bin/"*
  tar -czf "$TEST_ARCHIVE" -C "$TEST_ROOT/package" go

  cat >"$TEST_ROOT/bin/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'curl %s\n' "$*" >>"$TEST_EVENTS"
[[ ${TEST_CURL_STATUS:-0} == 0 ]] || exit "$TEST_CURL_STATUS"
[[ "$1" == -fsSL && "$2" == https://go.dev/dl/go1.27.4.darwin-arm64.tar.gz && "$3" == -o ]]
cp "$TEST_ARCHIVE" "$4"
EOF
  cat >"$TEST_ROOT/bin/shasum" <<'EOF'
#!/usr/bin/env bash
printf '%s  %s\n' "$TEST_SHA256" "$3"
EOF
  chmod 0755 "$TEST_ROOT/bin/"*
  PATH="$TEST_ROOT/bin:$PATH"
  export PATH
}

teardown() {
  rm -rf "$TEST_ROOT"
}

@test "Go installs into local opt and reuses the installation without changing native user data" {
  mkdir -p "$HOME/go/pkg/mod" "$HOME/.local/opt/go/custom"
  touch "$HOME/go/pkg/mod/keep" "$HOME/.local/opt/go/custom/keep"

  run "$MACOS_DIR/maintenance/go.sh"
  [ "$status" -eq 0 ]
  local root="$HOME/.local/opt/go/go1.27.4"
  [ -x "$root/bin/go" ]
  [ -x "$root/bin/gofmt" ]
  [ "$(<"$root/.codespace-version")" = 1.27.4 ]
  [ "$(readlink "$HOME/.local/opt/go/go1.27")" = go1.27.4 ]
  [ "$HOME/.local/opt/go/go1.27/bin/go" -ef "$root/bin/go" ]
  rm "$HOME/.local/opt/go/go1.27"
  run "$MACOS_DIR/maintenance/go.sh"
  [ "$status" -eq 0 ]
  [ "$(wc -l <"$TEST_EVENTS" | tr -d ' ')" = 1 ]
  [ "$HOME/.local/opt/go/go1.27/bin/go" -ef "$root/bin/go" ]
  [ -f "$HOME/go/pkg/mod/keep" ]
  [ -f "$HOME/.local/opt/go/custom/keep" ]
  [ -z "$(find "$TMPDIR" -mindepth 1 -print -quit)" ]
}

@test "Go checksum failure preserves the managed installation and unrelated data" {
  mkdir -p "$HOME/.local/opt/go/go1.27.4" "$HOME/.local/opt/custom-runtime"
  touch "$HOME/.local/opt/go/go1.27.4/keep" "$HOME/.local/opt/custom-runtime/keep"
  TEST_SHA256=invalid
  export TEST_SHA256

  run "$MACOS_DIR/maintenance/go.sh"
  [ "$status" -eq 1 ]
  [[ "$output" == *'checksum mismatch'* ]]
  [ -f "$HOME/.local/opt/go/go1.27.4/keep" ]
  [ -f "$HOME/.local/opt/custom-runtime/keep" ]
  [ -z "$(find "$TMPDIR" -mindepth 1 -print -quit)" ]
}

@test "Go download failure cleans temporary files without creating an installation" {
  TEST_CURL_STATUS=22
  export TEST_CURL_STATUS
  run "$MACOS_DIR/maintenance/go.sh"
  [ "$status" -eq 22 ]
  [ ! -e "$HOME/.local/opt/go" ]
  [ -z "$(find "$TMPDIR" -mindepth 1 -print -quit)" ]
}

@test "Go rejects an incomplete archive before replacing the installation" {
  rm "$TEST_ROOT/package/go/bin/gofmt"
  tar -czf "$TEST_ARCHIVE" -C "$TEST_ROOT/package" go
  mkdir -p "$HOME/.local/opt/go/go1.27.4"
  touch "$HOME/.local/opt/go/go1.27.4/keep"

  run "$MACOS_DIR/maintenance/go.sh"

  [ "$status" -eq 1 ]
  [ -f "$HOME/.local/opt/go/go1.27.4/keep" ]
  [ ! -e "$HOME/.local/opt/go/go1.27.4.installing" ]
  [ -z "$(find "$TMPDIR" -mindepth 1 -print -quit)" ]
}

@test "Go extraction failure cleans staging and preserves the installation" {
  printf 'not an archive\n' >"$TEST_ARCHIVE"
  mkdir -p "$HOME/.local/opt/go/go1.27.4"
  touch "$HOME/.local/opt/go/go1.27.4/keep"

  run "$MACOS_DIR/maintenance/go.sh"

  [ "$status" -ne 0 ]
  [ -f "$HOME/.local/opt/go/go1.27.4/keep" ]
  [ ! -e "$HOME/.local/opt/go/go1.27.4.installing" ]
  [ -z "$(find "$TMPDIR" -mindepth 1 -print -quit)" ]
}
