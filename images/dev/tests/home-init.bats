#!/usr/bin/env bats

setup_file() {
  bats_require_minimum_version 1.5.0
  HELPER="${BATS_TEST_DIRNAME}/../rootfs/opt/codespace/bin/home-init"
  export HELPER
}

setup() {
  TEST_ROOT=$(mktemp -d "${BATS_TEST_TMPDIR}/home-init.XXXXXX")
  mkdir -p "${TEST_ROOT}/bin" "${TEST_ROOT}/home"
  # deploy key 目录沙箱, 让写死的 /home/x/.ssh 落到临时目录而非测试机真实路径.
  export TEST_ROOT TEST_EVENTS="${TEST_ROOT}/events" SSH_DIR="${TEST_ROOT}/home/.ssh"

  # sudo/chown/seed 桩为记录事件, 只验证顺序与退出码.
  cat >"${TEST_ROOT}/bin/sudo" <<'EOF'
#!/usr/bin/env bash
exec "$@"
EOF
  cat >"${TEST_ROOT}/bin/chown" <<'EOF'
#!/usr/bin/env bash
printf 'chown %s\n' "$*" >>"${TEST_EVENTS}"
EOF
  cat >"${TEST_ROOT}/bin/seed-vscode-extensions" <<'EOF'
#!/usr/bin/env bash
printf 'seeded\n' >>"${TEST_EVENTS}"
EOF
  chmod +x "${TEST_ROOT}/bin/"*

  # 把脚本里的绝对路径外部编排(ssh 目录/dotfiles/agent-playbook/cp)换成无害沙箱, 保留控制流.
  sed \
    -e "s#/opt/codespace/bin/seed-vscode-extensions#seed-vscode-extensions#g" \
    -e "s#/home/x/.ssh#${SSH_DIR}#g" \
    -e "s#bash /opt/devspace/dotfiles/setup.sh .*#printf 'dotfiles\\\\n' >>\"${TEST_EVENTS}\"#g" \
    -e "s#bash /opt/agent-playbook/install.sh#printf 'playbook\\\\n' >>\"${TEST_EVENTS}\"#g" \
    -e "s#cp /opt/devspace/images/dev/dev-environment.md .*#:#g" \
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
  grep -qx "chown 5230:5230 /home/x/.vscode-server /home/x/.trae /home/x/.trae-cn /home/x/.trae-server /home/x/.trae-cn-server" "${TEST_EVENTS}"
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

  # 复跑幂等: 公钥保持不变.
  local first_public_key
  first_public_key=$(<"${SSH_DIR}/repo_id_ed25519.pub")
  run "${TEST_ROOT}/helper"
  [[ ${status} -eq 0 ]]
  [[ $(<"${SSH_DIR}/repo_id_ed25519.pub") == "${first_public_key}" ]]
}

@test "home init fails when a setup step fails" {
  cat >"${TEST_ROOT}/bin/seed-vscode-extensions" <<'EOF'
#!/usr/bin/env bash
exit 7
EOF
  chmod +x "${TEST_ROOT}/bin/seed-vscode-extensions"

  run "${TEST_ROOT}/helper"

  [[ ${status} -eq 7 ]]
}
