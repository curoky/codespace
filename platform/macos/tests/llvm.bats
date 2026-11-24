#!/usr/bin/env bats

setup() {
  MACOS_DIR="$(cd "$BATS_TEST_DIRNAME/.." && pwd -P)"
  TEST_ROOT="$(mktemp -d)"
  HOME="$TEST_ROOT/client home"
  TMPDIR="$TEST_ROOT/tmp"
  TEST_ARCHIVE="$TEST_ROOT/llvm.tar.xz"
  TEST_EVENTS="$TEST_ROOT/events"
  TEST_SHA256="$(sed -n 's/^expected_sha256="\(.*\)"$/\1/p' "$MACOS_DIR/maintenance/llvm.sh")"
  export HOME TMPDIR TEST_ROOT TEST_ARCHIVE TEST_EVENTS TEST_SHA256
  mkdir -p "$HOME" "$TMPDIR" "$TEST_ROOT/bin" "$TEST_ROOT/package/LLVM/bin"
  for executable in clang clang++ clang-format clangd llvm-config; do
    printf '#!/usr/bin/env bash\nexit 0\n' >"$TEST_ROOT/package/LLVM/bin/$executable"
    chmod 0755 "$TEST_ROOT/package/LLVM/bin/$executable"
  done
  tar -cJf "$TEST_ARCHIVE" -C "$TEST_ROOT/package" LLVM

  cat >"$TEST_ROOT/bin/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'curl %s\n' "$*" >>"$TEST_EVENTS"
[[ ${TEST_CURL_STATUS:-0} == 0 ]] || exit "$TEST_CURL_STATUS"
[[ "$1" == -fsSL && "$2" == https://github.com/llvm/llvm-project/releases/download/llvmorg-23.1.2/LLVM-23.1.2-macOS-ARM64.tar.xz && "$3" == -o ]]
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

@test "LLVM installs a complete SDK into local opt and reuses it without downloading again" {
  mkdir -p "$HOME/.local/opt/llvm/custom"
  touch "$HOME/.local/opt/llvm/custom/keep"
  run "$MACOS_DIR/maintenance/llvm.sh"
  [ "$status" -eq 0 ]
  local root="$HOME/.local/opt/llvm/llvm23.1.2"
  for executable in clang clang++ clang-format clangd llvm-config; do
    [ -x "$root/bin/$executable" ]
  done
  [ "$(<"$root/.codespace-version")" = 23.1.2 ]
  [ "$(readlink "$HOME/.local/opt/llvm/llvm23")" = llvm23.1.2 ]
  [ "$HOME/.local/opt/llvm/llvm23/bin/clang" -ef "$root/bin/clang" ]
  rm "$HOME/.local/opt/llvm/llvm23"
  run "$MACOS_DIR/maintenance/llvm.sh"
  [ "$status" -eq 0 ]
  [ "$(wc -l <"$TEST_EVENTS" | tr -d ' ')" = 1 ]
  [ "$HOME/.local/opt/llvm/llvm23/bin/clang" -ef "$root/bin/clang" ]
  [ -f "$HOME/.local/opt/llvm/custom/keep" ]
  [ ! -e "${root}.installing" ]
  [ -z "$(find "$TMPDIR" -mindepth 1 -print -quit)" ]
}

@test "LLVM checksum failure preserves managed and unrelated installations" {
  mkdir -p "$HOME/.local/opt/llvm/llvm23.1.2" "$HOME/.local/opt/custom-runtime"
  touch "$HOME/.local/opt/llvm/llvm23.1.2/keep" "$HOME/.local/opt/custom-runtime/keep"
  TEST_SHA256=invalid
  export TEST_SHA256
  run "$MACOS_DIR/maintenance/llvm.sh"
  [ "$status" -eq 1 ]
  [[ "$output" == *'checksum mismatch'* ]]
  [ -f "$HOME/.local/opt/llvm/llvm23.1.2/keep" ]
  [ -f "$HOME/.local/opt/custom-runtime/keep" ]
  [ -z "$(find "$TMPDIR" -mindepth 1 -print -quit)" ]
}

@test "LLVM download failure cleans temporary files without creating an installation" {
  TEST_CURL_STATUS=22
  export TEST_CURL_STATUS
  run "$MACOS_DIR/maintenance/llvm.sh"
  [ "$status" -eq 22 ]
  [ ! -e "$HOME/.local/opt/llvm" ]
  [ -z "$(find "$TMPDIR" -mindepth 1 -print -quit)" ]
}

@test "LLVM rejects an incomplete SDK before replacing the managed installation" {
  mkdir -p "$HOME/.local/opt/llvm/llvm23.1.2"
  touch "$HOME/.local/opt/llvm/llvm23.1.2/keep"
  rm "$TEST_ROOT/package/LLVM/bin/clangd"
  tar -cJf "$TEST_ARCHIVE" -C "$TEST_ROOT/package" LLVM
  run "$MACOS_DIR/maintenance/llvm.sh"
  [ "$status" -eq 1 ]
  [ -f "$HOME/.local/opt/llvm/llvm23.1.2/keep" ]
  [ ! -e "$HOME/.local/opt/llvm/llvm23.1.2.installing" ]
  [ -z "$(find "$TMPDIR" -mindepth 1 -print -quit)" ]
}
