#!/usr/bin/env bats

setup_file() {
  bats_require_minimum_version 1.5.0
}

setup() {
  MACOS_DIR="$(cd "$BATS_TEST_DIRNAME/.." && pwd -P)"
  REPO_ROOT="$(cd "$MACOS_DIR/../.." && pwd -P)"
  WORKSPACE_DIR="$REPO_ROOT/platform/container/workspace"
  SSH_DIR="$MACOS_DIR/rootfs/Users/x/.ssh/codespace"
  TEST_ROOT="$(mktemp -d "${BATS_TEST_TMPDIR}/ssh-assets.XXXXXX")"
  cp "$SSH_DIR/login_key" "$TEST_ROOT/login_key"
  chmod 0600 "$TEST_ROOT/login_key"
  mkdir "$TEST_ROOT/bin"
  cat >"$TEST_ROOT/bin/ssh" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@"
EOF
  chmod +x "$TEST_ROOT/bin/ssh"
  PATH="$TEST_ROOT/bin:$PATH"
  export PATH
}

teardown() {
  rm -rf "$TEST_ROOT"
}

@test "client login key matches the image authorized key" {
  local authorized_key public_key
  authorized_key="$(awk '{ print $1 " " $2 }' \
    "$WORKSPACE_DIR/rootfs/home/x/.ssh/authorized_keys")"

  run ssh-keygen -y -f "$TEST_ROOT/login_key"
  public_key="$(printf '%s\n' "$output" | awk '{ print $1 " " $2 }')"

  [ "$status" -eq 0 ]
  [ "$public_key" = "$authorized_key" ]
}

@test "client known host matches the image host key" {
  local host_key
  host_key="$(awk '{ print "codespace " $1 " " $2 }' \
    "$WORKSPACE_DIR/rootfs/etc/ssh/ssh_host_ed25519_key.pub")"

  [ "$(<"$SSH_DIR/known_hosts/codespace")" = "$host_key" ]
}

@test "client config hardcodes the Workspace image contract" {
  run /usr/bin/ssh -G -F "$SSH_DIR/config" \
    codespace-workspace-23456_home_codespace_debug

  [ "$status" -eq 0 ]
  [[ "$output" == *$'user x\n'* ]]
  [[ "$output" == *$'hostname 127.0.0.1\n'* ]]
  [[ "$output" == *$'stricthostkeychecking true\n'* ]]
  [[ "$output" == *$'hostkeyalgorithms ssh-ed25519\n'* ]]
  [[ "$output" == *$'hostkeyalias codespace\n'* ]]
  [[ "$output" == *$'controlmaster false\n'* ]]
  [[ "$output" != *$'controlpath '* ]]
  [[ "$output" == *'proxycommand ~/.ssh/codespace/proxy %n'* ]]
}

@test "proxy derives the Host route and forwarding port from the alias" {
  run "$SSH_DIR/proxy" \
    codespace-workspace-23456_home-dev.example_codespace_debug

  [ "$status" -eq 0 ]
  [ "${lines[0]}" = "-W" ]
  [ "${lines[1]}" = "127.0.0.1:23456" ]
  [ "${lines[2]}" = "home-dev.example" ]
}

@test "proxy rejects aliases outside the fixed contract" {
  run "$SSH_DIR/proxy" \
    codespace-workspace-19999_home_codespace_debug

  [ "$status" -eq 2 ]
  [[ "$output" == "invalid Workspace SSH Host port: 19999" ]]
}
