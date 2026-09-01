#!/usr/bin/env bats

setup_file() {
  bats_require_minimum_version 1.5.0
  HELPER="${BATS_TEST_DIRNAME}/../rootfs/opt/codespace/bin/codespace-workspace-bootstrap"
  export HELPER
}

setup() {
  TEST_ROOT=$(mktemp -d "${BATS_TEST_TMPDIR}/codespace-workspace-bootstrap.XXXXXX")
  mkdir -p "${TEST_ROOT}/bin" "${TEST_ROOT}/control"
  export TEST_ROOT

  cat >"${TEST_ROOT}/bin/s6-setuidgid" <<'EOF'
#!/usr/bin/env bash
shift
exec "$@"
EOF
  cat >"${TEST_ROOT}/bin/timeout" <<'EOF'
#!/usr/bin/env bash
shift 2
exec "$@"
EOF
  cat >"${TEST_ROOT}/bin/codespace-git-checkout" <<'EOF'
#!/usr/bin/env bash
printf 'checkout:%s:%s\n' "$1" "$2" >>"${TEST_EVENTS}"
EOF
  cat >"${TEST_ROOT}/bin/codespace-workspace-open-path" <<'EOF'
#!/usr/bin/env bash
printf 'open:%s\n' "$1" >>"${TEST_EVENTS}"
EOF
  chmod +x "${TEST_ROOT}/bin/"*

  sed \
    -e "s#/run/codespace-control#${TEST_ROOT}/control#g" \
    -e "s#/opt/codespace/bin/codespace-git-checkout#${TEST_ROOT}/bin/codespace-git-checkout#g" \
    -e "s#/opt/codespace/bin/codespace-workspace-open-path#${TEST_ROOT}/bin/codespace-workspace-open-path#g" \
    "${HELPER}" >"${TEST_ROOT}/helper"
  chmod +x "${TEST_ROOT}/helper"
  export PATH="${TEST_ROOT}/bin:${PATH}"
  export TEST_EVENTS="${TEST_ROOT}/events"
}

teardown() {
  rm -rf -- "${TEST_ROOT}"
}

@test "git workspace checks out and prepares the open path" {
  run env \
    CODESPACE_WORKSPACE_TYPE=git \
    CODESPACE_CLONE_URL=git@example:repo \
    CODESPACE_CLONE_PATH=/workspace/repo \
    CODESPACE_OPEN_PATH=/workspace/repo \
    "${TEST_ROOT}/helper"

  [[ ${status} -eq 0 ]]
  [[ $(<"${TEST_EVENTS}") == $'checkout:git@example:repo:/workspace/repo\nopen:/workspace/repo' ]]
  [[ -f ${TEST_ROOT}/control/bootstrap.ready ]]
  [[ ! -e ${TEST_ROOT}/control/bootstrap.failed ]]
}

@test "repo workspace starts after provider authorization" {
  touch "${TEST_ROOT}/control/provider-ready"

  run env \
    CODESPACE_WORKSPACE_TYPE=repo \
    CODESPACE_CLONE_URL=git@example:repo \
    CODESPACE_CLONE_PATH=/workspace/repo \
    CODESPACE_OPEN_PATH=/workspace/repo \
    "${TEST_ROOT}/helper"

  [[ ${status} -eq 0 ]]
  [[ $(<"${TEST_EVENTS}") == $'checkout:git@example:repo:/workspace/repo\nopen:/workspace/repo' ]]
}

@test "blank workspace only prepares the open path" {
  run env \
    CODESPACE_WORKSPACE_TYPE=blank \
    CODESPACE_CLONE_PATH=/workspace \
    CODESPACE_OPEN_PATH=/workspace \
    "${TEST_ROOT}/helper"

  [[ ${status} -eq 0 ]]
  [[ $(<"${TEST_EVENTS}") == "open:/workspace" ]]
  [[ -f ${TEST_ROOT}/control/bootstrap.ready ]]
}

@test "bootstrap records command failures" {
  cat >"${TEST_ROOT}/bin/codespace-git-checkout" <<'EOF'
#!/usr/bin/env bash
exit 7
EOF
  chmod +x "${TEST_ROOT}/bin/codespace-git-checkout"

  run env \
    CODESPACE_WORKSPACE_TYPE=git \
    CODESPACE_CLONE_URL=git@example:repo \
    CODESPACE_CLONE_PATH=/workspace/repo \
    CODESPACE_OPEN_PATH=/workspace/repo \
    "${TEST_ROOT}/helper"

  [[ ${status} -eq 7 ]]
  [[ $(<"${TEST_ROOT}/control/bootstrap.failed") == "workspace bootstrap repository checkout failed (7)" ]]
}
