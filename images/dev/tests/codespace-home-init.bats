#!/usr/bin/env bats

setup_file() {
  bats_require_minimum_version 1.5.0
  HELPER="${BATS_TEST_DIRNAME}/../rootfs/opt/codespace/bin/codespace-home-init"
  export HELPER
}

setup() {
  TEST_ROOT=$(mktemp -d "${BATS_TEST_TMPDIR}/codespace-home-init.XXXXXX")
  mkdir -p "${TEST_ROOT}/bin" "${TEST_ROOT}/control"
  export TEST_ROOT

  cat >"${TEST_ROOT}/bin/s6-setuidgid" <<'EOF'
#!/usr/bin/env bash
shift
exec "$@"
EOF
  cat >"${TEST_ROOT}/bin/s6-pause" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  cat >"${TEST_ROOT}/home-setup" <<'EOF'
#!/usr/bin/env bash
printf 'initialized\n' >>"${TEST_EVENTS}"
EOF
  chmod +x "${TEST_ROOT}/bin/"* "${TEST_ROOT}/home-setup"

  sed \
    -e "s#/run/codespace-control#${TEST_ROOT}/control#g" \
    -e "s#/opt/codespace/bin/codespace-home-setup#${TEST_ROOT}/home-setup#g" \
    "${HELPER}" >"${TEST_ROOT}/helper"
  chmod +x "${TEST_ROOT}/helper"
  export PATH="${TEST_ROOT}/bin:${PATH}"
  export TEST_EVENTS="${TEST_ROOT}/events"
}

teardown() {
  rm -rf -- "${TEST_ROOT}"
}

@test "managed workspace publishes completed home initialization" {
  run env CODESPACE_WORKSPACE_TYPE=blank "${TEST_ROOT}/helper"

  [[ ${status} -eq 0 ]]
  [[ $(<"${TEST_EVENTS}") == "initialized" ]]
  [[ -f ${TEST_ROOT}/control/home.ready ]]
  [[ ! -e ${TEST_ROOT}/control/home.failed ]]
}

@test "managed workspace publishes home initialization failure" {
  cat >"${TEST_ROOT}/home-setup" <<'EOF'
#!/usr/bin/env bash
exit 7
EOF
  chmod +x "${TEST_ROOT}/home-setup"

  run env CODESPACE_WORKSPACE_TYPE=blank "${TEST_ROOT}/helper"

  [[ ${status} -eq 0 ]]
  [[ $(<"${TEST_ROOT}/control/home.failed") == "home initialization failed (7)" ]]
}

@test "completed managed home initialization is reused after restart" {
  touch "${TEST_ROOT}/control/home.ready"

  run env CODESPACE_WORKSPACE_TYPE=blank "${TEST_ROOT}/helper"

  [[ ${status} -eq 0 ]]
  [[ ! -e ${TEST_EVENTS} ]]
}

@test "generic image initializes home without managed markers" {
  run "${TEST_ROOT}/helper"

  [[ ${status} -eq 0 ]]
  [[ $(<"${TEST_EVENTS}") == "initialized" ]]
  [[ ! -e ${TEST_ROOT}/control/home.ready ]]
  [[ ! -e ${TEST_ROOT}/control/home.failed ]]
}
