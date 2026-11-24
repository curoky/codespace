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
    "$TEST_ROOT/bundle/jdk-27+35/Contents/Home/bin" \
    "$TEST_ROOT/bundle/jdk-27+35/Contents/_CodeSignature"
  printf '#!/usr/bin/env bash\nexit 0\n' >"$TEST_ROOT/bundle/jdk-27+35/Contents/Home/bin/java"
  cp "$TEST_ROOT/bundle/jdk-27+35/Contents/Home/bin/java" \
    "$TEST_ROOT/bundle/jdk-27+35/Contents/Home/bin/javac"
  chmod 0755 "$TEST_ROOT/bundle/jdk-27+35/Contents/Home/bin/"*
  touch "$TEST_ROOT/bundle/jdk-27+35/Contents/_CodeSignature/CodeResources"
  tar -czf "$TEST_ARCHIVE" -C "$TEST_ROOT/bundle" jdk-27+35

  cat >"$TEST_ROOT/bin/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'curl %s\n' "$*" >>"$TEST_EVENTS"
if [[ ${TEST_CURL_STATUS:-0} != 0 ]]; then
  exit "$TEST_CURL_STATUS"
fi
while [[ $# -gt 0 ]]; do
  if [[ $1 == -o ]]; then
    cp "$TEST_ARCHIVE" "$2"
    exit 0
  fi
  shift
done
exit 1
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

@test "Java installs only the runtime with the Linux directory layout" {
  run "$MACOS_DIR/maintenance/java-runtime.sh"
  [ "$status" -eq 0 ]

  local root="$HOME/.local/opt/java/openjdk27"
  [ -x "$root/bin/java" ]
  [ -x "$root/bin/javac" ]
  [ "$(<"$root/.codespace-version")" = '27+35' ]
  [ ! -e "$root/Contents" ]
  [ ! -e "$root/CodeResources" ]
  [ ! -e "$HOME/.local/opt/java/openjdk8" ]
  grep -Fq 'OpenJDK27U-jdk_aarch64_mac_hotspot_27_35.tar.gz' "$TEST_EVENTS"
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
  rm "$TEST_ROOT/bundle/jdk-27+35/Contents/Home/bin/javac"
  tar -czf "$TEST_ARCHIVE" -C "$TEST_ROOT/bundle" jdk-27+35

  run "$MACOS_DIR/maintenance/java-runtime.sh"
  [ "$status" -eq 1 ]
  [ -f "$HOME/.local/opt/java/openjdk27/keep" ]
  run find "$TMPDIR" -mindepth 1
  [ "$output" = '' ]
}

@test "Java tools use their own Python environment and preserve installed packages" {
  mkdir -p "$HOME/.local/bin" "$HOME/.local/share/uv/bin" \
    "$HOME/.local/opt/java/openjdk27/bin" "$HOME/.local/opt/java/tools/envs/custom"
  touch "$HOME/.local/opt/java/tools/envs/custom/keep"
  install -m 0755 "$TEST_ROOT/bundle/jdk-27+35/Contents/Home/bin/java" \
    "$HOME/.local/opt/java/openjdk27/bin/java"
  install -m 0755 "$TEST_ROOT/bundle/jdk-27+35/Contents/Home/bin/java" \
    "$HOME/.local/share/uv/bin/python3.14"
  cat >"$HOME/.local/bin/uv" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'uv %s\npython %s\nvenv %s\n' "$*" "$UV_PYTHON_INSTALL_DIR" "${VIRTUAL_ENV:-}" >>"$TEST_EVENTS"
mkdir -p "$UV_PROJECT_ENVIRONMENT/bin"
printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$*"\n' >"$UV_PROJECT_ENVIRONMENT/bin/python"
chmod 0755 "$UV_PROJECT_ENVIRONMENT/bin/python"
EOF
  chmod 0755 "$HOME/.local/bin/uv"
  VIRTUAL_ENV="$TEST_ROOT/caller-env"
  UV_PROJECT_ENVIRONMENT="$TEST_ROOT/caller-project"
  export VIRTUAL_ENV UV_PROJECT_ENVIRONMENT

  run "$MACOS_DIR/maintenance/java-tools.sh"
  [ "$status" -eq 0 ]
  local installer="$HOME/.local/opt/java/java-tool"
  [ -x "$installer/java-tool" ]
  [ -x "$installer/.venv/bin/python" ]
  cmp "$installer/java-tool.py" "$MACOS_DIR/../container/workspace/tools/java-tool/java-tool.py"
  grep -Fqx "python $HOME/.local/share/uv/python" "$TEST_EVENTS"
  grep -Fqx 'venv ' "$TEST_EVENTS"
  [ ! -e "$TEST_ROOT/caller-project" ]
  [ -f "$HOME/.local/opt/java/tools/envs/custom/keep" ]

  run "$installer/java-tool" --help
  [ "$status" -eq 0 ]
  [ "$output" = "$installer/java-tool.py --help" ]
  run "$MACOS_DIR/maintenance/java-tools.sh"
  [ "$status" -eq 0 ]
  [ -f "$HOME/.local/opt/java/tools/envs/custom/keep" ]
}

@test "Java tools fail before copying source when dependencies are missing" {
  run "$MACOS_DIR/maintenance/java-tools.sh"
  [ "$status" -eq 1 ]
  [ ! -e "$HOME/.local/opt/java/java-tool" ]
}
