#!/usr/bin/env bats

setup_file() {
  bats_require_minimum_version 1.5.0
}

setup() {
  MACOS_DIR="$(cd "$BATS_TEST_DIRNAME/.." && pwd -P)"
  TEST_ROOT="$(mktemp -d)"
  HOME="$TEST_ROOT/home"
  export HOME
  mkdir -p "$HOME"

  # shellcheck source=platform/macos/install-v2.sh
  source "$MACOS_DIR/install-v2.sh"

  # shellcheck disable=SC2329 # install_binman_bundle invokes this test stub indirectly.
  sudo() {
    "$@"
  }
}

teardown() {
  rm -rf "$TEST_ROOT"
}

make_bm_bundle() {
  local root="$TEST_ROOT/bundle-root"
  mkdir -p "$root/bm/bin" "$root/bm/store/binman"
  printf '#!/usr/bin/env bash\nexit 0\n' >"$root/bm/bin/bm"
  chmod +x "$root/bm/bin/bm"
  ln -s ../store/binman/bin/bm "$root/bm/bin/binman"
  tar -C "$root" -czf "$TEST_ROOT/bm.tar.gz" bm
}

@test "installs a packaged bm tree and replaces the managed prefix" {
  make_bm_bundle
  local destination="$TEST_ROOT/opt/bm"
  mkdir -p "$destination"
  touch "$destination/stale"

  run install_binman_bundle "$TEST_ROOT/bm.tar.gz" "$destination"

  [ "$status" -eq 0 ]
  [ -x "$destination/bin/bm" ]
  [ -L "$destination/bin/binman" ]
  [ ! -e "$destination/stale" ]
}

@test "rejects a bundle with paths outside the bm root" {
  local root="$TEST_ROOT/invalid-root"
  local destination="$TEST_ROOT/opt/bm"
  mkdir -p "$root/other" "$destination"
  touch "$root/other/file" "$destination/existing"
  tar -C "$root" -czf "$TEST_ROOT/invalid.tar.gz" other

  run install_binman_bundle "$TEST_ROOT/invalid.tar.gz" "$destination"

  [ "$status" -ne 0 ]
  [ -e "$destination/existing" ]
}
