#!/usr/bin/env bats

setup_file() {
  bats_require_minimum_version 1.5.0
  HELPER="${BATS_TEST_DIRNAME}/../rootfs/opt/codespace/bin/init-home"
  export HELPER
}

setup() {
  TEST_ROOT=$(mktemp -d "${BATS_TEST_TMPDIR}/init-home.XXXXXX")
  HOME_DIR="${TEST_ROOT}/home"
  SHARE_DIR="${TEST_ROOT}/share"
  SSH_DIR="${HOME_DIR}/.ssh"
  export TEST_ROOT HOME_DIR SHARE_DIR SSH_DIR TEST_EVENTS="${TEST_ROOT}/events"
  mkdir -p "${TEST_ROOT}/bin" "${HOME_DIR}" \
    "${SHARE_DIR}/trae" "${SHARE_DIR}/vscode" "${SHARE_DIR}/agent-playbook"
  printf '{}\n' >"${SHARE_DIR}/trae/sandbox.json"
  printf 'model = "test"\n' >"${SHARE_DIR}/trae/traecli.toml"
  printf '{}\n' >"${SHARE_DIR}/vscode/remote-settings.json"
  printf '# Workspace rules\n' >"${SHARE_DIR}/agent-rules.md"
  cat >"${SHARE_DIR}/agent-playbook/install.sh" <<'EOF'
#!/usr/bin/env bash
printf 'playbook\n' >>"${TEST_EVENTS}"
EOF
  chmod +x "${SHARE_DIR}/agent-playbook/install.sh"

  # sudo/chown/seed 桩为记录事件，只验证顺序与退出码。
  cat >"${TEST_ROOT}/bin/sudo" <<'EOF'
#!/usr/bin/env bash
exec "$@"
EOF
  cat >"${TEST_ROOT}/bin/chown" <<'EOF'
#!/usr/bin/env bash
printf 'chown %s\n' "$*" >>"${TEST_EVENTS}"
EOF
  cat >"${TEST_ROOT}/bin/seed-editor-extensions" <<'EOF'
#!/usr/bin/env bash
printf 'seeded\n' >>"${TEST_EVENTS}"
EOF
  chmod +x "${TEST_ROOT}/bin/"*

  # 将 helper 的固定镜像路径映射到测试沙箱，保留原控制流。
  sed \
    -e "s#/opt/codespace/bin/seed-editor-extensions#seed-editor-extensions#g" \
    -e "s#/home/x#${HOME_DIR}#g" \
    -e "s#readonly SHARE_DIR=/opt/codespace/share#readonly SHARE_DIR=${SHARE_DIR}#g" \
    "${HELPER}" >"${TEST_ROOT}/helper"
  chmod +x "${TEST_ROOT}/helper"
  export PATH="${TEST_ROOT}/bin:${PATH}"
}

teardown() {
  rm -rf -- "${TEST_ROOT}"
}

@test "home init chowns the five IDE home mounts before setup" {
  run "${TEST_ROOT}/helper"

  [[ ${status} -eq 0 ]]
  grep -qx "chown 5230:5230 ${HOME_DIR}/.vscode-server ${HOME_DIR}/.trae ${HOME_DIR}/.trae-cn ${HOME_DIR}/.trae-server ${HOME_DIR}/.trae-cn-server" "${TEST_EVENTS}"
  grep -qx "seeded" "${TEST_EVENTS}"
  # chown must precede the seed/setup steps.
  local chown_line seed_line
  chown_line=$(grep -n "^chown " "${TEST_EVENTS}" | cut -d: -f1)
  seed_line=$(grep -nx "seeded" "${TEST_EVENTS}" | cut -d: -f1)
  [[ ${seed_line} -gt ${chown_line} ]]
}

@test "home init generates and reuses the deploy key" {
  run "${TEST_ROOT}/helper"

  [[ ${status} -eq 0 ]]
  [[ -f ${SSH_DIR}/repo_id_ed25519 ]]
  [[ -f ${SSH_DIR}/repo_id_ed25519.pub ]]
  local mode
  mode=$(stat -c %a "${SSH_DIR}/repo_id_ed25519" 2>/dev/null ||
    stat -f %Lp "${SSH_DIR}/repo_id_ed25519")
  [[ ${mode} == 600 ]]
  [[ -f ${HOME_DIR}/.trae/sandbox.json ]]
  [[ -f ${HOME_DIR}/.vscode-server/data/Machine/settings.json ]]

  # 复跑幂等: 公钥保持不变.
  local first_public_key
  first_public_key=$(<"${SSH_DIR}/repo_id_ed25519.pub")
  run "${TEST_ROOT}/helper"
  [[ ${status} -eq 0 ]]
  [[ $(<"${SSH_DIR}/repo_id_ed25519.pub") == "${first_public_key}" ]]
}

@test "home init fails when a setup step fails" {
  cat >"${TEST_ROOT}/bin/seed-editor-extensions" <<'EOF'
#!/usr/bin/env bash
exit 7
EOF
  chmod +x "${TEST_ROOT}/bin/seed-editor-extensions"

  run "${TEST_ROOT}/helper"

  [[ ${status} -eq 7 ]]
}
