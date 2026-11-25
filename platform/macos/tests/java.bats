#!/usr/bin/env bats

setup_file() {
  bats_require_minimum_version 1.5.0
}

setup() {
  MACOS_DIR="$(cd "$BATS_TEST_DIRNAME/.." && pwd -P)"
  TEST_ROOT="$(mktemp -d)"
  HOME="$TEST_ROOT/client home"
  TMPDIR="$TEST_ROOT/tmp"
  TEST_ARCHIVE="$TEST_ROOT/jdk.tar.gz"
  TEST_EVENTS="$TEST_ROOT/events"
  TEST_SHA256="$(sed -n 's/^expected_sha256="\(.*\)"$/\1/p' "$MACOS_DIR/maintenance/java-runtime.sh")"
  export HOME TMPDIR TEST_ROOT TEST_ARCHIVE TEST_EVENTS TEST_SHA256
  mkdir -p "$HOME" "$TMPDIR" "$TEST_ROOT/bin" \
    "$TEST_ROOT/bundle/jdk-27.0.1.1+4/Contents/Home/bin" \
    "$TEST_ROOT/bundle/jdk-27.0.1.1+4/Contents/_CodeSignature"
  printf '#!/usr/bin/env bash\nexit 0\n' >"$TEST_ROOT/bundle/jdk-27.0.1.1+4/Contents/Home/bin/java"
  cp "$TEST_ROOT/bundle/jdk-27.0.1.1+4/Contents/Home/bin/java" \
    "$TEST_ROOT/bundle/jdk-27.0.1.1+4/Contents/Home/bin/javac"
  chmod 0755 "$TEST_ROOT/bundle/jdk-27.0.1.1+4/Contents/Home/bin/"*
  touch "$TEST_ROOT/bundle/jdk-27.0.1.1+4/Contents/_CodeSignature/CodeResources"
  tar -czf "$TEST_ARCHIVE" -C "$TEST_ROOT/bundle" jdk-27.0.1.1+4

  cat >"$TEST_ROOT/bin/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'curl %s\n' "$*" >>"$TEST_EVENTS"
if [[ ${TEST_CURL_STATUS:-0} != 0 ]]; then
  exit "$TEST_CURL_STATUS"
fi
while [[ $# -gt 0 ]]; do
  if [[ $1 == -o ]]; then
    if [[ "$2" == */cs.gz ]]; then
      cp "$TEST_CS_ARCHIVE" "$2"
    else
      cp "$TEST_ARCHIVE" "$2"
    fi
    exit 0
  fi
  shift
done
exit 1
EOF
  cat >"$TEST_ROOT/bin/shasum" <<'EOF'
#!/usr/bin/env bash
if [[ "$3" == */cs.gz ]]; then
  printf '%s  %s\n' "$TEST_CS_SHA256" "$3"
else
  printf '%s  %s\n' "$TEST_SHA256" "$3"
fi
EOF
  chmod 0755 "$TEST_ROOT/bin/"*
  PATH="$TEST_ROOT/bin:$PATH"
  export PATH
}

teardown() {
  rm -rf "$TEST_ROOT"
}

@test "Java installs only the runtime with the Linux directory layout" {
  run "$MACOS_DIR/maintenance/java-runtime.sh"
  [ "$status" -eq 0 ]

  local root="$HOME/.local/opt/java/openjdk27"
  [ -x "$root/bin/java" ]
  [ -x "$root/bin/javac" ]
  [ "$(<"$root/.codespace-version")" = '27.0.1.1+4' ]
  [ ! -e "$root/Contents" ]
  [ ! -e "$root/CodeResources" ]
  [ ! -e "$HOME/.local/opt/java/openjdk8" ]
  grep -Fq 'OpenJDK27U-jdk_aarch64_mac_hotspot_27.0.1.1_4.tar.gz' "$TEST_EVENTS"
  run find "$TMPDIR" -mindepth 1
  [ "$output" = '' ]
}

@test "Java installation is repeatable without downloading again" {
  run "$MACOS_DIR/maintenance/java-runtime.sh"
  [ "$status" -eq 0 ]
  run "$MACOS_DIR/maintenance/java-runtime.sh"
  [ "$status" -eq 0 ]
  [ "$(wc -l <"$TEST_EVENTS" | tr -d ' ')" = 1 ]
}

@test "Java checksum failure preserves the managed installation and unrelated data" {
  mkdir -p "$HOME/.local/opt/java/openjdk27" "$HOME/.local/opt/java/custom-jdk"
  touch "$HOME/.local/opt/java/openjdk27/keep" "$HOME/.local/opt/java/custom-jdk/keep"
  TEST_SHA256=invalid
  export TEST_SHA256

  run "$MACOS_DIR/maintenance/java-runtime.sh"
  [ "$status" -eq 1 ]
  [[ "$output" == *'checksum mismatch'* ]]
  [ -f "$HOME/.local/opt/java/openjdk27/keep" ]
  [ -f "$HOME/.local/opt/java/custom-jdk/keep" ]
  run find "$TMPDIR" -mindepth 1
  [ "$output" = '' ]
}

@test "Java download failure cleans temporary files without installing" {
  TEST_CURL_STATUS=22
  export TEST_CURL_STATUS
  run "$MACOS_DIR/maintenance/java-runtime.sh"
  [ "$status" -eq 22 ]
  [ ! -e "$HOME/.local/opt/java/openjdk27" ]
  run find "$TMPDIR" -mindepth 1
  [ "$output" = '' ]
}

@test "Java rejects an incomplete archive before replacing the managed installation" {
  mkdir -p "$HOME/.local/opt/java/openjdk27"
  touch "$HOME/.local/opt/java/openjdk27/keep"
  rm "$TEST_ROOT/bundle/jdk-27.0.1.1+4/Contents/Home/bin/javac"
  tar -czf "$TEST_ARCHIVE" -C "$TEST_ROOT/bundle" jdk-27.0.1.1+4

  run "$MACOS_DIR/maintenance/java-runtime.sh"
  [ "$status" -eq 1 ]
  [ -f "$HOME/.local/opt/java/openjdk27/keep" ]
  run find "$TMPDIR" -mindepth 1
  [ "$output" = '' ]
}

prepare_java_tool() {
  TEST_CS_ARCHIVE="$TEST_ROOT/cs.gz"
  TEST_CS_SHA256="$(sed -n 's/^cs_sha256="\(.*\)"$/\1/p' "$MACOS_DIR/maintenance/java-tools.sh")"
  export TEST_CS_ARCHIVE TEST_CS_SHA256
  printf '#!/usr/bin/env bash\nexit 0\n' | gzip >"$TEST_CS_ARCHIVE"
  mkdir -p "$HOME/.local/bin"
  cat >"$HOME/.local/bin/oras" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'oras %s\n' "$*" >>"$TEST_EVENTS"
[[ "$1" == pull && "$2" == ghcr.io/curoky/codespace:java-tool-darwin-arm64 && "$3" == -o ]]
[[ ${TEST_ORAS_STATUS:-0} == 0 ]] || exit "$TEST_ORAS_STATUS"
printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$*"\n' >"$4/java-tool"
tar -czf "$4/java-tool.tar.gz" -C "$4" java-tool
rm "$4/java-tool"
EOF
  chmod 0755 "$HOME/.local/bin/oras"
}

@test "Java tools download a standalone helper and preserve installed packages" {
  prepare_java_tool
  mkdir -p \
    "$HOME/.local/opt/java/tools/envs/custom"
  touch "$HOME/.local/opt/java/tools/envs/custom/keep"
  VIRTUAL_ENV="$TEST_ROOT/caller-env"
  UV_PROJECT_ENVIRONMENT="$TEST_ROOT/caller-project"
  export VIRTUAL_ENV UV_PROJECT_ENVIRONMENT

  run "$MACOS_DIR/maintenance/java-tools.sh"
  [ "$status" -eq 0 ]
  local installer="$HOME/.local/opt/java/java-tool"
  [ -x "$installer" ]
  [ -x "$HOME/.local/opt/java/cs" ]
  [ ! -e "$installer/.venv" ]
  grep -Fq 'oras pull ghcr.io/curoky/codespace:java-tool-darwin-arm64' "$TEST_EVENTS"
  [ ! -e "$HOME/.local/opt/go" ]
  [ ! -e "$HOME/.local/opt/java/openjdk27" ]
  [ ! -e "$TEST_ROOT/caller-project" ]
  [ -f "$HOME/.local/opt/java/tools/envs/custom/keep" ]

  run "$installer" --help
  [ "$status" -eq 0 ]
  [ "$output" = --help ]
  run "$MACOS_DIR/maintenance/java-tools.sh"
  [ "$status" -eq 0 ]
  [ -f "$HOME/.local/opt/java/tools/envs/custom/keep" ]
}

@test "Coursier checksum failure preserves the existing helper and installed packages" {
  prepare_java_tool
  mkdir -p "$HOME/.local/opt/java/tools/envs/custom"
  printf 'existing helper\n' >"$HOME/.local/opt/java/java-tool"
  touch "$HOME/.local/opt/java/tools/envs/custom/keep"
  TEST_CS_SHA256=invalid
  export TEST_CS_SHA256
  run "$MACOS_DIR/maintenance/java-tools.sh"
  [ "$status" -eq 1 ]
  [[ "$output" == *'Coursier checksum mismatch'* ]]
  [ "$(<"$HOME/.local/opt/java/java-tool")" = 'existing helper' ]
  [ -f "$HOME/.local/opt/java/tools/envs/custom/keep" ]
  run find "$TMPDIR" -mindepth 1
  [ "$output" = '' ]
}

@test "Java tools fail before changing installations when ORAS is missing" {
  run "$MACOS_DIR/maintenance/java-tools.sh"
  [ "$status" -eq 1 ]
  [ ! -e "$HOME/.local/opt/java/java-tool" ]
}

@test "Java tool download failure preserves the existing helper and packages" {
  prepare_java_tool
  mkdir -p "$HOME/.local/opt/java/tools/envs/custom"
  touch "$HOME/.local/opt/java/tools/envs/custom/keep"
  printf 'existing helper\n' >"$HOME/.local/opt/java/java-tool"
  export TEST_ORAS_STATUS=22

  run "$MACOS_DIR/maintenance/java-tools.sh"
  [ "$status" -eq 22 ]
  [ "$(<"$HOME/.local/opt/java/java-tool")" = 'existing helper' ]
  [ -f "$HOME/.local/opt/java/tools/envs/custom/keep" ]
  run find "$TMPDIR" -mindepth 1
  [ "$output" = '' ]
}
