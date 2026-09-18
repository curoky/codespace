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
  cp "$SSH_DIR/workspace_login_key_ed25519" "$TEST_ROOT/workspace_login_key_ed25519"
  chmod 0600 "$TEST_ROOT/workspace_login_key_ed25519"
}

teardown() {
  rm -rf "$TEST_ROOT"
}

@test "client login key matches the image authorized key" {
  local authorized_key public_key
  authorized_key="$(awk '{ print $1 " " $2 }' \
    "$WORKSPACE_DIR/rootfs/home/x/.ssh/authorized_keys")"

  run ssh-keygen -y -f "$TEST_ROOT/workspace_login_key_ed25519"
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
    space-codespace-debug-home

  [ "$status" -eq 0 ]
  [[ "$output" == *$'user x\n'* ]]
  [[ "$output" == *$'hostname 127.0.0.1\n'* ]]
  [[ "$output" == *$'batchmode yes\n'* ]]
  [[ "$output" == *$'stricthostkeychecking true\n'* ]]
  [[ "$output" == *$'hostkeyalgorithms ssh-ed25519\n'* ]]
  [[ "$output" == *$'hostkeyalias codespace\n'* ]]
  [[ "$output" == *$'controlmaster false\n'* ]]
  [[ "$output" != *$'controlpath '* ]]
  [[ $'\n'"$output"$'\n' != *$'\nproxycommand '* ]]
  grep -Fqx 'Include ~/.ssh/codespace/workspaces/*' "$SSH_DIR/config"
}

@test "client config loads a persisted Workspace route" {
  local alias config routes
  alias="space-codespace-debug-home"
  config="$TEST_ROOT/config"
  routes="$TEST_ROOT/workspaces"
  mkdir "$routes"
  cat >"$routes/$alias" <<'EOF'
Host space-codespace-debug-home
  Port 23456
  ProxyCommand ssh -o BatchMode=yes -W %h:%p home
EOF
  sed "s|~/.ssh/codespace/workspaces/\\*|$routes/*|" "$SSH_DIR/config" >"$config"

  run /usr/bin/ssh -G -F "$config" "$alias"

  [ "$status" -eq 0 ]
  [[ "$output" == *$'port 23456\n'* ]]
  [[ "$output" == *$'hostname 127.0.0.1\n'* ]]
  [[ "$output" == *'proxycommand ssh -o BatchMode=yes -W %h:%p home'* ]]
}

@test "ordinary Host aliases do not use Workspace routes" {
  run /usr/bin/ssh -G -F "$SSH_DIR/config" home-dev.example
  [ "$status" -eq 0 ]
  [[ "$output" == *$'hostname home-dev.example\n'* ]]
  [[ $'\n'"$output"$'\n' != *$'\nproxycommand '* ]]
}
