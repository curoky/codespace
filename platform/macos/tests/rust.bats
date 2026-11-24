#!/usr/bin/env bats

setup() {
  MACOS_DIR="$(cd "$BATS_TEST_DIRNAME/.." && pwd -P)"
  TEST_ROOT="$(mktemp -d)"
  HOME="$TEST_ROOT/client home"
  TEST_EVENTS="$TEST_ROOT/events"
  TMPDIR="$TEST_ROOT/tmp"
  export HOME TEST_ROOT TEST_EVENTS TMPDIR
  mkdir -p "$HOME" "$TEST_ROOT/bin" "$TMPDIR"

  cat >"$TEST_ROOT/rustup" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'rustup %s\ncargo %s\nrustup-home %s\n' \
  "$*" "$CARGO_HOME" "$RUSTUP_HOME" >>"$TEST_EVENTS"
mkdir -p "$RUSTUP_HOME/toolchains/stable"
if [[ "$1 $2" == 'component add' && "${TEST_COMPONENT_FAILURE:-}" == 1 ]]; then
  exit 1
fi
EOF
  cat >"$TEST_ROOT/bin/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'curl %s\n' "$*" >>"$TEST_EVENTS"
[[ "${TEST_DOWNLOAD_FAILURE:-}" != 1 ]] || exit 22
[[ "$1" == -fsSL && "$2" == https://sh.rustup.rs && "$3" == -o ]]
cat >"$4" <<'INSTALLER'
#!/usr/bin/env bash
set -euo pipefail
printf 'bootstrap %s\ncargo %s\nrustup-home %s\n' \
  "$*" "$CARGO_HOME" "$RUSTUP_HOME" >>"$TEST_EVENTS"
mkdir -p "$CARGO_HOME/bin"
cp "$TEST_ROOT/rustup" "$CARGO_HOME/bin/rustup"
INSTALLER
EOF
  chmod 0755 "$TEST_ROOT/rustup" "$TEST_ROOT/bin/curl"
  PATH="$TEST_ROOT/bin:$PATH"
  export PATH
}

teardown() {
  rm -rf "$TEST_ROOT"
}

@test "Rust maintenance installs the stable SDK and proxies under local opt without changing user Cargo data" {
  mkdir -p "$HOME/.cargo/registry"
  printf 'cache\n' >"$HOME/.cargo/registry/keep"
  printf 'shell config\n' >"$HOME/.zshrc"
  CARGO_HOME="$TEST_ROOT/caller-cargo"
  RUSTUP_HOME="$TEST_ROOT/caller-rustup"
  export CARGO_HOME RUSTUP_HOME

  run "$MACOS_DIR/maintenance/rust.sh"
  [ "$status" -eq 0 ]
  [ -x "$HOME/.local/opt/rust/cargo/bin/rustup" ]
  grep -Fqx 'bootstrap -y --no-modify-path --default-toolchain none' "$TEST_EVENTS"
  grep -Fqx "cargo $HOME/.local/opt/rust/cargo" "$TEST_EVENTS"
  grep -Fqx "rustup-home $HOME/.local/opt/rust/rustup" "$TEST_EVENTS"
  grep -Fqx 'rustup toolchain install stable --profile default' "$TEST_EVENTS"
  grep -Fqx 'rustup component add rust-src rust-analyzer llvm-tools --toolchain stable' "$TEST_EVENTS"
  grep -Fqx 'rustup component remove rust-docs --toolchain stable' "$TEST_EVENTS"
  grep -Fqx 'rustup default stable' "$TEST_EVENTS"
  [ "$(<"$HOME/.cargo/registry/keep")" = cache ]
  [ "$(<"$HOME/.zshrc")" = 'shell config' ]
  [ ! -e "$TEST_ROOT/caller-cargo" ]
  [ ! -e "$TEST_ROOT/caller-rustup" ]
  [ -z "$(find "$TMPDIR" -mindepth 1 -print -quit)" ]
}

@test "Rust maintenance reuses its rustup installation without deleting other toolchains or runtimes" {
  run "$MACOS_DIR/maintenance/rust.sh"
  [ "$status" -eq 0 ]
  mkdir -p "$HOME/.local/opt/rust/rustup/toolchains/custom" "$HOME/.local/opt/custom-runtime"
  touch "$HOME/.local/opt/rust/rustup/toolchains/custom/keep" "$HOME/.local/opt/custom-runtime/keep"

  run "$MACOS_DIR/maintenance/rust.sh"
  [ "$status" -eq 0 ]
  [ "$(grep -Fc 'curl -fsSL' "$TEST_EVENTS")" = 1 ]
  [ "$(grep -Fc 'rustup toolchain install stable' "$TEST_EVENTS")" = 2 ]
  [ -f "$HOME/.local/opt/rust/rustup/toolchains/custom/keep" ]
  [ -f "$HOME/.local/opt/custom-runtime/keep" ]
}

@test "Rust maintenance cleans its temporary download on failure without creating an installation" {
  TEST_DOWNLOAD_FAILURE=1
  export TEST_DOWNLOAD_FAILURE
  run "$MACOS_DIR/maintenance/rust.sh"
  [ "$status" -eq 22 ]
  [ ! -e "$HOME/.local/opt/rust" ]
  [ -z "$(find "$TMPDIR" -mindepth 1 -print -quit)" ]
}

@test "Rust maintenance fails immediately when a required component cannot be installed" {
  TEST_COMPONENT_FAILURE=1
  export TEST_COMPONENT_FAILURE
  run "$MACOS_DIR/maintenance/rust.sh"
  [ "$status" -eq 1 ]
  run grep -F 'rustup default stable' "$TEST_EVENTS"
  [ "$status" -eq 1 ]
}
