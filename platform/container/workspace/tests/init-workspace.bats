#!/usr/bin/env bats

setup_file() {
  bats_require_minimum_version 1.5.0
  HELPER="${BATS_TEST_DIRNAME}/../rootfs/opt/codespace/bin/init-workspace"
  if [[ -n ${CODESPACE_TEST_BASH-} ]]; then
    HELPER_BASH=${CODESPACE_TEST_BASH}
  elif [[ -x /opt/homebrew/opt/bash/bin/bash ]]; then
    HELPER_BASH=/opt/homebrew/opt/bash/bin/bash
  elif [[ -x /usr/local/opt/bash/bin/bash ]]; then
    HELPER_BASH=/usr/local/opt/bash/bin/bash
  else
    HELPER_BASH=$(command -v bash)
  fi
  export HELPER HELPER_BASH
}

setup() {
  STUB_BIN=$(mktemp -d "${BATS_TEST_TMPDIR}/stub.XXXXXX")
  TEST_EVENTS="${STUB_BIN}/events"
  TEST_SUDO_EVENTS="${STUB_BIN}/sudo-events"
  REAL_GREP=$(command -v grep)
  export STUB_BIN TEST_EVENTS TEST_SUDO_EVENTS REAL_GREP
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

# 明文场景(CODESPACE_WORKSPACE_KEY 未设)直接跳过挂载.
@test "workspace init skips plaintext workspaces" {
  run --separate-stderr env -u CODESPACE_WORKSPACE_KEY PATH="${PATH}" "${HELPER_BASH}" "${HELPER}"

  [[ ${status} -eq 0 ]]
  [[ ${output} == "CODESPACE_WORKSPACE_KEY unset; Workspace encryption disabled, using plaintext /workspace" ]]
  [[ -z ${stderr} ]]
  grep -qx "install -d -o 5230 -g 5230 -m 0700 -- /workspace /workspace.enc /upload /cache" \
    "${TEST_SUDO_EVENTS}"
}

@test "workspace init mounts encrypted workspaces with the codespace key" {
  run --separate-stderr env CODESPACE_WORKSPACE_KEY=secret \
    PATH="${PATH}" "${HELPER_BASH}" "${HELPER}"

  [[ ${status} -eq 0 ]]
  [[ -z ${stderr} ]]
  grep -qx "install -d -o 5230 -g 5230 -m 0700 -- /workspace /workspace.enc /upload /cache" \
    "${TEST_SUDO_EVENTS}"
  [[ $(wc -l <"${TEST_EVENTS}") -eq 2 ]]
  # The extpass argument must retain this literal for evaluation by gocryptfs.
  # shellcheck disable=SC2016
  local key_expression='${CODESPACE_WORKSPACE_KEY}'
  grep -qF -- "-init -extpass echo \"${key_expression}\" /workspace.enc" \
    "${TEST_EVENTS}"
  grep -qF -- "-extpass echo \"${key_expression}\" -allow_other /workspace.enc /workspace" \
    "${TEST_EVENTS}"
}
