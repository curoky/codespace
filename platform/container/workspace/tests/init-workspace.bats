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
  WORKSPACE_KEY_FILE="${STUB_BIN}/workspace-key"
  REAL_GREP=$(command -v grep)
  export STUB_BIN TEST_EVENTS TEST_SUDO_EVENTS WORKSPACE_KEY_FILE REAL_GREP
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

# 明文场景（Workspace key secret 未挂载）直接跳过挂载。
@test "workspace init skips plaintext workspaces" {
  run --separate-stderr env PATH="${PATH}" "${HELPER_BASH}" "${HELPER}" "${WORKSPACE_KEY_FILE}"

  [[ ${status} -eq 0 ]]
  [[ ${output} == "Workspace key secret unavailable; encryption disabled, using plaintext /workspace" ]]
  [[ -z ${stderr} ]]
  grep -qx "install -d -o 5230 -g 5230 -m 0700 -- /workspace /workspace.enc /upload /cache" \
    "${TEST_SUDO_EVENTS}"
}

@test "workspace init mounts encrypted workspaces with the codespace key" {
  printf '%s' secret >"${WORKSPACE_KEY_FILE}"
  run --separate-stderr env PATH="${PATH}" "${HELPER_BASH}" "${HELPER}" "${WORKSPACE_KEY_FILE}"

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
