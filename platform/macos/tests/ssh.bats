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
  cat >"$TEST_ROOT/bin/curl" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" >"$TEST_ROOT/curl-args"
printf '%s' "$CURL_RESPONSE"
exit "$CURL_STATUS"
EOF
  chmod +x "$TEST_ROOT/bin/ssh" "$TEST_ROOT/bin/curl"
  export TEST_ROOT
  export CURL_RESPONSE=$'home-dev.example 23456\n\n200'
  export CURL_STATUS=0
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
    space-codespace-debug-home

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

@test "proxy resolves the full alias through the local control plane" {
  run "$SSH_DIR/proxy" space-service-api-my-debug-home-dev.example

  [ "$status" -eq 0 ]
  [ "${lines[0]}" = "-W" ]
  [ "${lines[1]}" = "127.0.0.1:23456" ]
  [ "${lines[2]}" = "home-dev.example" ]
  [ "$(<"$TEST_ROOT/curl-args")" = "$(printf '%s\n' \
    --disable --silent --show-error --fail --noproxy '*' \
    --connect-timeout 2 --max-time 30 --write-out '\n%{http_code}' \
    'http://127.0.0.1:8003/api/ssh/space-service-api-my-debug-home-dev.example')" ]
}

@test "proxy rejects aliases outside the fixed contract before querying" {
  local alias
  for alias in invalid-alias 'space-a-b-!' 'space-a-b-h?query' $'space-a-b-home\n'; do
    run "$SSH_DIR/proxy" "$alias"
    [ "$status" -eq 2 ]
    [[ "$output" == 'invalid Workspace SSH alias:'* ]]
    [ ! -e "$TEST_ROOT/curl-args" ]
  done
  run "$SSH_DIR/proxy"
  [ "$status" -eq 2 ]
}

@test "proxy rejects failed lookups and timeouts without opening SSH" {
  local failure
  for failure in 7 22 28; do
    run --separate-stderr env CURL_STATUS="$failure" CURL_RESPONSE='' \
      "$SSH_DIR/proxy" space-codespace-debug-home
    [ "$status" -eq 1 ]
    [ -z "$output" ]
    [[ "$stderr" == *'check the local codespace control plane'* ]]
  done
}

@test "proxy rejects redirects and non-success HTTP status" {
  local code
  for code in 301 404 409 500; do
    run --separate-stderr env CURL_RESPONSE=$'home 23456\n\n'"$code" \
      "$SSH_DIR/proxy" space-codespace-debug-home
    [ "$status" -eq 1 ]
    [ -z "$output" ]
    [[ "$stderr" == 'unexpected Workspace SSH route response' ]]
  done
}

@test "proxy rejects malformed routes and recursive Hosts" {
  local route
  for route in '' 'home 19999' 'home 30000' 'home 23456 extra' '-oProxyCommand=bad 23456' \
    $'home 23456\nother 23456' 'home 23456;command' 'space-home 23456'; do
    run --separate-stderr env CURL_RESPONSE="$route"$'\n\n200' \
      "$SSH_DIR/proxy" space-codespace-debug-home
    [ "$status" -eq 2 ]
    [ -z "$output" ]
  done
}

@test "proxy preserves SSH stdin and returns its exit status" {
  cat >"$TEST_ROOT/bin/ssh" <<'EOF'
#!/usr/bin/env bash
cat
exit 37
EOF
  run bash -c 'printf "SSH payload" | "$1" space-codespace-debug-home' _ "$SSH_DIR/proxy"
  [ "$status" -eq 37 ]
  [ "$output" = 'SSH payload' ]
}

@test "ordinary Host aliases do not use the Workspace proxy" {
  run /usr/bin/ssh -G -F "$SSH_DIR/config" home-dev.example
  [ "$status" -eq 0 ]
  [[ "$output" == *$'hostname home-dev.example\n'* ]]
  [[ $'\n'"$output"$'\n' != *$'\nproxycommand '* ]]
}
