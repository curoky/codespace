#!/usr/bin/env bats

setup_file() {
  bats_require_minimum_version 1.5.0
}

setup() {
  TOOL="$BATS_TEST_TMPDIR/tool"
  SCRIPT="$TOOL/csecret.sh"
  HOME="$BATS_TEST_TMPDIR/home"
  CSECRET_TEST_KEY="$BATS_TEST_TMPDIR/passphrase"
  REAL_GPG="$(command -v gpg)"
  export HOME CSECRET_TEST_KEY REAL_GPG
  CSECRET_TEST_KEY_PATH="$BATS_TEST_TMPDIR/key-path"
  export CSECRET_TEST_KEY_PATH
  mkdir -p "$TOOL" "$HOME" "$BATS_TEST_TMPDIR/bin"
  cp "$BATS_TEST_DIRNAME/csecret.sh" "$SCRIPT"
  printf fixture-passphrase >"$CSECRET_TEST_KEY"

  mkdir -p "$HOME/.config/codespace"
  printf 'secrets:\n  codespace_workspace_key: fixture-passphrase\n' \
    >"$HOME/.config/codespace/config.yaml"

  cat >"$BATS_TEST_TMPDIR/bin/uname" <<'EOF'
#!/bin/sh
printf 'Darwin\n'
EOF
  # Redirect the Linux mount only; macOS reads real YAML and GPG stays real.
  cat >"$BATS_TEST_TMPDIR/bin/cat" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ $# == 1 && $1 == /run/secrets/codespace_workspace_key ]]; then
  printf '%s' "$1" >"$CSECRET_TEST_KEY_PATH"
  exec /bin/cat "$CSECRET_TEST_KEY"
fi
exec /bin/cat "$@"
EOF
  cat >"$BATS_TEST_TMPDIR/bin/gpg" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
args=()
for arg do
  if [[ $arg == --symmetric && ${TEST_FAIL_ENCRYPT:-0} == 1 ]]; then
    exit 42
  fi
  args+=("$arg")
done
exec "$REAL_GPG" "${args[@]}"
EOF
  chmod 0755 "$BATS_TEST_TMPDIR/bin/"*
  export PATH="$BATS_TEST_TMPDIR/bin:$PATH"

  cat >"$TOOL/secrets.json" <<'EOF'
{
  "token": "fixture-token",
  "empty": "",
  "multiline": " leading and trailing \n\n",
  "llmbox_access_token": "fixture\"token\\\n$token",
  "llmbox_expires_at": "2030-01-01T00:00:00.123456789Z",
  "OAUTH_DOMAIN": "fixture-oauth",
  "MODEL_DOMAIN": "fixture-model",
  "OAUTH_CLIENT_ID": "fixture-client",
  "LLMBOX_SOURCE": "fixture-source"
}
EOF
}

prepare_custom_job() {
  mkdir -p "$HOME/.codex" "$HOME/.local/bin"
  ln -s "$SCRIPT" "$HOME/.local/bin/csecret"
  printf 'printf installed > "%s/installed"\n' "$HOME" >"$BATS_TEST_TMPDIR/install.sh"
  jq --arg url "file://$BATS_TEST_TMPDIR/install.sh" '.traecli_download_curl = $url' \
    "$TOOL/secrets.json" >"$BATS_TEST_TMPDIR/updated.json"
  mv "$BATS_TEST_TMPDIR/updated.json" "$TOOL/secrets.json"
  "$SCRIPT" encrypt
  cp "$TOOL/secrets.json" "$BATS_TEST_TMPDIR/valid.json"
  cp "$BATS_TEST_DIRNAME/../../rootfs/home/x/.codex/llmbox.config.toml.template" "$HOME/.codex/"
  sed "s@/home/x@$HOME@g" "$BATS_TEST_DIRNAME/../../rootfs/etc/s6/s6-rc.d/custom-job/run.sh" >"$BATS_TEST_TMPDIR/custom-job.sh"
  printf 'previous profile\n' >"$HOME/.codex/llmbox.config.toml"
  printf 'previous credentials\n' >"$HOME/.codex/llmbox.auth.json"
  chmod 0755 "$HOME/.codex"
  chmod 0644 "$HOME/.codex/llmbox.config.toml" "$HOME/.codex/llmbox.auth.json"
  cp "$HOME/.codex/llmbox.config.toml" "$BATS_TEST_TMPDIR/previous.toml"
  cp "$HOME/.codex/llmbox.auth.json" "$BATS_TEST_TMPDIR/previous.auth"
}

@test "encrypt and decrypt roundtrip with private files and no stdout" {
  cp "$TOOL/secrets.json" "$BATS_TEST_TMPDIR/expected"
  run --separate-stderr "$SCRIPT" encrypt
  [ "$status" -eq 0 ]
  [ -z "$output" ]
  [ "$(stat -c %a "$TOOL/secrets.json.gpg")" = 600 ]
  unlink "$TOOL/secrets.json"
  run --separate-stderr "$SCRIPT" decrypt
  [ "$status" -eq 0 ]
  [ -z "$output" ]
  cmp "$BATS_TEST_TMPDIR/expected" "$TOOL/secrets.json"
  [ "$(stat -c %a "$TOOL/secrets.json")" = 600 ]
}

@test "get preserves raw values without creating plaintext" {
  "$SCRIPT" encrypt
  for key in token empty multiline llmbox_access_token llmbox_expires_at; do
    jq -j --arg key "$key" '.[$key]' "$TOOL/secrets.json" >"$BATS_TEST_TMPDIR/expected"
    "$SCRIPT" get "$key" >"$BATS_TEST_TMPDIR/actual"
    cmp "$BATS_TEST_TMPDIR/expected" "$BATS_TEST_TMPDIR/actual"
  done
  unlink "$TOOL/secrets.json"
  "$SCRIPT" get token >"$BATS_TEST_TMPDIR/actual"
  [ "$(<"$BATS_TEST_TMPDIR/actual")" = fixture-token ]
  [ ! -e "$TOOL/secrets.json" ]
  run "$SCRIPT" get missing
  [ "$status" -ne 0 ]
  [[ "$output" == *'secret not found: missing'* ]]
  [ -z "$(find "$TOOL" -name 'secrets.json.*' ! -name 'secrets.json.gpg' -print -quit)" ]
}

@test "get locates ciphertext next to the real script from any directory" {
  "$SCRIPT" encrypt
  mkdir -p "$HOME/.local/bin"
  ln -s "$SCRIPT" "$HOME/.local/bin/csecret"
  cd "$HOME"
  run --separate-stderr "$HOME/.local/bin/csecret" get token
  [ "$status" -eq 0 ]
  [ "$output" = fixture-token ]
}

@test "macOS reads Codespace YAML and Linux reads the mounted key" {
  for platform in Darwin Linux; do
    printf '#!/bin/sh\nprintf "%s\\n"\n' "$platform" >"$BATS_TEST_TMPDIR/bin/uname"
    chmod 0755 "$BATS_TEST_TMPDIR/bin/uname"
    "$SCRIPT" encrypt
    if [[ $platform == Linux ]]; then
      [ "$(<"$CSECRET_TEST_KEY_PATH")" = /run/secrets/codespace_workspace_key ]
    fi
    run --separate-stderr "$SCRIPT" get token
    [ "$status" -eq 0 ]
    [ "$output" = fixture-token ]
  done
}

@test "macOS parses quoted YAML keys and aliases" {
  printf 'fixture: # with spaces' >"$CSECRET_TEST_KEY"
  printf '#!/bin/sh\nprintf "Linux\\n"\n' >"$BATS_TEST_TMPDIR/bin/uname"
  "$SCRIPT" encrypt
  cat >"$HOME/.config/codespace/config.yaml" <<'EOF'
workspace_key: &workspace_key "fixture: # with spaces"
secrets:
  codespace_workspace_key: *workspace_key
EOF
  printf '#!/bin/sh\nprintf "Darwin\\n"\n' >"$BATS_TEST_TMPDIR/bin/uname"
  run --separate-stderr "$SCRIPT" get token
  [ "$status" -eq 0 ]
  [ "$output" = fixture-token ]
}

@test "missing or invalid macOS key config preserves both files and exposes no values" {
  "$SCRIPT" encrypt
  cp "$TOOL/secrets.json.gpg" "$BATS_TEST_TMPDIR/previous.gpg"
  cp "$TOOL/secrets.json" "$BATS_TEST_TMPDIR/previous.json"
  for data in '{}' 'secrets: null' 'secrets: {}' \
    'secrets: {codespace_workspace_key: null}' \
    'secrets: {codespace_workspace_key: 123}' \
    'secrets: {codespace_workspace_key: true}' \
    'secrets: {codespace_workspace_key: {nested: private-fixture}}' \
    'secrets: {codespace_workspace_key: [private-fixture]}' \
    'secrets: {codespace_workspace_key: ""}' \
    'secrets: {codespace_workspace_key: "  "}' \
    'secrets: {codespace_workspace_key: "\u00a0\u2003"}' \
    'secrets: {codespace_workspace_key: [private-fixture, ' \
    $'secrets: {codespace_workspace_key: fixture-passphrase}\n---\n{}'; do
    printf '%s\n' "$data" >"$HOME/.config/codespace/config.yaml"
    for command in encrypt decrypt; do
      run --separate-stderr "$SCRIPT" "$command"
      [ "$status" -ne 0 ]
      [ -z "$output" ]
      [[ "$stderr" == *'cannot read codespace_workspace_key from Codespace config'* ]]
      [[ "$stderr" != *'private-fixture'* ]]
      cmp "$BATS_TEST_TMPDIR/previous.gpg" "$TOOL/secrets.json.gpg"
      cmp "$BATS_TEST_TMPDIR/previous.json" "$TOOL/secrets.json"
    done
  done
  unlink "$HOME/.config/codespace/config.yaml"
  mkdir -p "$HOME/.config/csecret"
  printf fixture-passphrase >"$HOME/.config/csecret/key"
  run --separate-stderr "$SCRIPT" get token
  [ "$status" -ne 0 ]
  [ -z "$output" ]
  [[ "$stderr" == *'cannot read codespace_workspace_key from Codespace config'* ]]
  [ -z "$(find "$TOOL" -name 'secrets.json.*' ! -name 'secrets.json.gpg' -print -quit)" ]
}

@test "macOS explicit keys override YAML merges regardless of field order" {
  "$SCRIPT" encrypt
  for data in '
defaults: &defaults
  codespace_workspace_key: inherited-fixture
secrets:
  codespace_workspace_key: fixture-passphrase
  <<: *defaults
' '
defaults: &defaults
  codespace_workspace_key: inherited-fixture
secrets:
  <<: *defaults
  codespace_workspace_key: fixture-passphrase
'; do
    printf '%s\n' "$data" >"$HOME/.config/codespace/config.yaml"
    run --separate-stderr "$SCRIPT" get token
    [ "$status" -eq 0 ]
    [ "$output" = fixture-token ]
  done
}

@test "failed encryption or decryption preserves existing targets" {
  "$SCRIPT" encrypt
  cp "$TOOL/secrets.json.gpg" "$BATS_TEST_TMPDIR/previous.gpg"
  export TEST_FAIL_ENCRYPT=1
  run "$SCRIPT" encrypt
  [ "$status" -eq 42 ]
  cmp "$BATS_TEST_TMPDIR/previous.gpg" "$TOOL/secrets.json.gpg"
  printf wrong-passphrase >"$CSECRET_TEST_KEY"
  printf 'secrets:\n  codespace_workspace_key: wrong-passphrase\n' \
    >"$HOME/.config/codespace/config.yaml"
  cp "$TOOL/secrets.json" "$BATS_TEST_TMPDIR/previous.json"
  run "$SCRIPT" decrypt
  [ "$status" -ne 0 ]
  cmp "$BATS_TEST_TMPDIR/previous.json" "$TOOL/secrets.json"
  [ -z "$(find "$TOOL" -name 'secrets.json.*' ! -name 'secrets.json.gpg' -print -quit)" ]
}

@test "invalid JSON or a non-object cannot replace valid ciphertext" {
  "$SCRIPT" encrypt
  cp "$TOOL/secrets.json.gpg" "$BATS_TEST_TMPDIR/previous.gpg"
  for data in '{"token":' '[]' 'null' ''; do
    printf '%s' "$data" >"$TOOL/secrets.json"
    run "$SCRIPT" encrypt
    [ "$status" -ne 0 ]
    cmp "$BATS_TEST_TMPDIR/previous.gpg" "$TOOL/secrets.json.gpg"
    [ -z "$(find "$TOOL" -name 'secrets.json.gpg.*' -print -quit)" ]
  done
  run --separate-stderr "$SCRIPT" get token
  [ "$status" -eq 0 ]
  [ "$output" = fixture-token ]
}

@test "Git excludes plaintext and editor files but keeps ciphertext" {
  cp "$BATS_TEST_DIRNAME/.gitignore" "$TOOL/.gitignore"
  git -C "$TOOL" init --quiet
  for file in secrets.json secrets.json~ secrets.json.gpg.XXXXXX \
    .secrets.json.swp .secrets.json.swo '.#secrets.json' '#secrets.json#'; do
    run git -C "$TOOL" -c core.excludesFile=/dev/null check-ignore --no-index "$file"
    [ "$status" -eq 0 ]
  done
  run git -C "$TOOL" -c core.excludesFile=/dev/null check-ignore --no-index secrets.json.gpg
  [ "$status" -eq 1 ]
}

@test "help needs no key and old commands are rejected" {
  unlink "$CSECRET_TEST_KEY"
  unlink "$HOME/.config/codespace/config.yaml"
  run "$SCRIPT" --help
  [ "$status" -eq 0 ]
  [ "$output" = 'Usage: csecret {get KEY|encrypt|decrypt}' ]
  for command in write list dump; do
    run "$SCRIPT" "$command"
    [ "$status" -eq 2 ]
  done
  run "$SCRIPT" get
  [ "$status" -eq 2 ]
  run "$SCRIPT" encrypt extra
  [ "$status" -eq 2 ]
  [ "$(readlink "$BATS_TEST_DIRNAME/../../rootfs/home/x/.local/bin/csecret")" = '../opt/csecret/csecret.sh' ]
}

@test "custom-job publishes profile and credential fields privately through csecret" {
  prepare_custom_job
  run --separate-stderr bash "$BATS_TEST_TMPDIR/custom-job.sh"
  [ "$status" -eq 0 ]
  [ -z "$output" ]
  [ "$(<"$HOME/installed")" = installed ]
  run grep -Eq '@[A-Z_]+@' "$HOME/.codex/llmbox.config.toml"
  [ "$status" -eq 1 ]
  grep -Fq 'client_id = "fixture-client"' "$HOME/.codex/llmbox.config.toml"
  jq '{access_token: .llmbox_access_token, expires_at: .llmbox_expires_at}' \
    "$TOOL/secrets.json" >"$BATS_TEST_TMPDIR/expected.auth"
  cmp "$BATS_TEST_TMPDIR/expected.auth" "$HOME/.codex/llmbox.auth.json"
  [ "$(stat -c %a "$HOME/.codex")" = 700 ]
  [ "$(stat -c %a "$HOME/.codex/llmbox.config.toml")" = 600 ]
  [ "$(stat -c %a "$HOME/.codex/llmbox.auth.json")" = 600 ]
  [ -z "$(find "$HOME/.codex" -name '.custom-job.*' -print -quit)" ]
}

@test "custom-job preserves both files and skips installation when any secret is missing" {
  prepare_custom_job
  for key in OAUTH_DOMAIN MODEL_DOMAIN OAUTH_CLIENT_ID LLMBOX_SOURCE traecli_download_curl \
    llmbox_access_token llmbox_expires_at; do
    jq --arg key "$key" 'del(.[$key])' "$BATS_TEST_TMPDIR/valid.json" >"$TOOL/secrets.json"
    "$SCRIPT" encrypt
    run bash "$BATS_TEST_TMPDIR/custom-job.sh"
    [ "$status" -ne 0 ]
    [[ "$output" == *"secret not found: $key"* ]]
    cmp "$BATS_TEST_TMPDIR/previous.toml" "$HOME/.codex/llmbox.config.toml"
    cmp "$BATS_TEST_TMPDIR/previous.auth" "$HOME/.codex/llmbox.auth.json"
    [ ! -e "$HOME/installed" ]
    [ -z "$(find "$HOME/.codex" -name '.custom-job.*' -print -quit)" ]
  done
}

@test "custom-job rejects malformed credential fields without leaking values or replacing files" {
  prepare_custom_job
  for value in '' 'invalid-fixture-expiry' '2030-02-30T00:00:00Z' \
    '2030-01-01T25:00:00Z' '2030-01-01T00:00:00+00:00'; do
    jq --arg value "$value" '.llmbox_expires_at = $value' \
      "$BATS_TEST_TMPDIR/valid.json" >"$TOOL/secrets.json"
    "$SCRIPT" encrypt
    run bash "$BATS_TEST_TMPDIR/custom-job.sh"
    [ "$status" -ne 0 ]
    [[ "$output" == *'invalid LLMBox credential fields'* ]]
    [[ "$output" != *'fixture'* ]]
    cmp "$BATS_TEST_TMPDIR/previous.toml" "$HOME/.codex/llmbox.config.toml"
    cmp "$BATS_TEST_TMPDIR/previous.auth" "$HOME/.codex/llmbox.auth.json"
    [ ! -e "$HOME/installed" ]
    [ -z "$(find "$HOME/.codex" -name '.custom-job.*' -print -quit)" ]
  done
  jq '.llmbox_access_token = ""' "$BATS_TEST_TMPDIR/valid.json" >"$TOOL/secrets.json"
  "$SCRIPT" encrypt
  run bash "$BATS_TEST_TMPDIR/custom-job.sh"
  [ "$status" -ne 0 ]
  cmp "$BATS_TEST_TMPDIR/previous.toml" "$HOME/.codex/llmbox.config.toml"
  cmp "$BATS_TEST_TMPDIR/previous.auth" "$HOME/.codex/llmbox.auth.json"
  [ ! -e "$HOME/installed" ]
  [ -z "$(find "$HOME/.codex" -name '.custom-job.*' -print -quit)" ]
}

@test "custom-job publishes expired credentials and leaves expiry policy to LLMBox" {
  prepare_custom_job
  jq '.llmbox_expires_at = "2000-01-01T00:00:00Z"' \
    "$BATS_TEST_TMPDIR/valid.json" >"$TOOL/secrets.json"
  "$SCRIPT" encrypt
  run bash "$BATS_TEST_TMPDIR/custom-job.sh"
  [ "$status" -eq 0 ]
  jq -e '.expires_at == "2000-01-01T00:00:00Z"' "$HOME/.codex/llmbox.auth.json" >/dev/null
}
