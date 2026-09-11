#!/usr/bin/env bats

setup_file() {
  bats_require_minimum_version 1.5.0
  HELPER_SOURCE="${BATS_TEST_DIRNAME}/../rootfs/opt/codespace/bin/init-workspace"
  if [[ -n ${CODESPACE_TEST_BASH-} ]]; then
    HELPER_BASH=${CODESPACE_TEST_BASH}
  elif [[ -x /opt/homebrew/opt/bash/bin/bash ]]; then
    HELPER_BASH=/opt/homebrew/opt/bash/bin/bash
  elif [[ -x /usr/local/opt/bash/bin/bash ]]; then
    HELPER_BASH=/usr/local/opt/bash/bin/bash
  else
    HELPER_BASH=$(command -v bash)
  fi
  export HELPER_SOURCE HELPER_BASH
}

setup() {
  STUB_BIN=$(mktemp -d "${BATS_TEST_TMPDIR}/stub.XXXXXX")
  TEST_EVENTS="${STUB_BIN}/events"
  TEST_SUDO_EVENTS="${STUB_BIN}/sudo-events"
  WORKSPACE_KEY_FILE="${STUB_BIN}/workspace-key"
  HELPER="${STUB_BIN}/init-workspace"
  REAL_GREP=$(command -v grep)
  export STUB_BIN TEST_EVENTS TEST_SUDO_EVENTS WORKSPACE_KEY_FILE HELPER REAL_GREP
  sed "s#/run/secrets/codespace_workspace_key#${WORKSPACE_KEY_FILE}#g" \
    "${HELPER_SOURCE}" >"${HELPER}"
  chmod +x "${HELPER}"
  cat >"${STUB_BIN}/sudo" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"${TEST_SUDO_EVENTS}"
EOF
  cat >"${STUB_BIN}/grep" <<'EOF'
#!/usr/bin/env bash
for argument in "$@"; do
  [[ $argument == /proc/mounts ]] && exit 1
done
exec "${REAL_GREP}" "$@"
EOF
  cat >"${STUB_BIN}/gocryptfs" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"${TEST_EVENTS}"
EOF
  chmod +x "${STUB_BIN}/sudo"
  chmod +x "${STUB_BIN}/grep"
  chmod +x "${STUB_BIN}/gocryptfs"
  export PATH="${STUB_BIN}:${PATH}"
}

@test "workspace init skips plaintext workspaces" {
  run --separate-stderr env CODESPACE_ENCRYPTED=false PATH="${PATH}" "${HELPER_BASH}" "${HELPER}"

  [[ ${status} -eq 0 ]]
  [[ ${output} == "Workspace encryption disabled, using plaintext /workspace" ]]
  [[ -z ${stderr} ]]
  grep -qx "install -d -o 5230 -g 5230 -m 0700 -- /workspace /workspace.enc /upload /cache" \
    "${TEST_SUDO_EVENTS}"
}

@test "workspace init mounts encrypted workspaces with the codespace key" {
  printf '%s' secret >"${WORKSPACE_KEY_FILE}"
  run --separate-stderr env CODESPACE_ENCRYPTED=true PATH="${PATH}" "${HELPER_BASH}" "${HELPER}"

  [[ ${status} -eq 0 ]]
  [[ -z ${stderr} ]]
  grep -qx "install -d -o 5230 -g 5230 -m 0700 -- /workspace /workspace.enc /upload /cache" \
    "${TEST_SUDO_EVENTS}"
  [[ $(wc -l <"${TEST_EVENTS}") -eq 2 ]]
  grep -qF -- "-init -extpass cat -- ${WORKSPACE_KEY_FILE} /workspace.enc" \
    "${TEST_EVENTS}"
  grep -qF -- "-extpass cat -- ${WORKSPACE_KEY_FILE} -allow_other /workspace.enc /workspace" \
    "${TEST_EVENTS}"
}

@test "workspace init fails when encryption key is unavailable" {
  run --separate-stderr env CODESPACE_ENCRYPTED=true PATH="${PATH}" "${HELPER_BASH}" "${HELPER}"

  [[ ${status} -ne 0 ]]
  [[ ${stderr} == "Encrypted Workspace requires a readable key secret" ]]
  [[ ! -e ${TEST_EVENTS} ]]
}

@test "workspace init rejects an invalid encryption flag" {
  run --separate-stderr env CODESPACE_ENCRYPTED=invalid PATH="${PATH}" "${HELPER_BASH}" "${HELPER}"

  [[ ${status} -ne 0 ]]
  [[ ${stderr} == "CODESPACE_ENCRYPTED must be true or false" ]]
  [[ ! -e ${TEST_SUDO_EVENTS} ]]
}

@test "workspace init requires an explicit encryption flag" {
  run --separate-stderr env -u CODESPACE_ENCRYPTED PATH="${PATH}" "${HELPER_BASH}" "${HELPER}"

  [[ ${status} -ne 0 ]]
  [[ ${stderr} == *"CODESPACE_ENCRYPTED must be true or false"* ]]
  [[ ! -e ${TEST_SUDO_EVENTS} ]]
}

@test "plaintext workspaces ignore an unrelated key secret" {
  printf '%s' secret >"${WORKSPACE_KEY_FILE}"
  run --separate-stderr env CODESPACE_ENCRYPTED=false PATH="${PATH}" "${HELPER_BASH}" "${HELPER}"

  [[ ${status} -eq 0 ]]
  [[ ! -e ${TEST_EVENTS} ]]
}
