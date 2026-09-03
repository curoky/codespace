#!/usr/bin/env bats

setup_file() {
  bats_require_minimum_version 1.5.0
  HELPER="${BATS_TEST_DIRNAME}/../rootfs/opt/codespace/bin/init-home"
  export HELPER
}

setup() {
  TEST_ROOT=$(mktemp -d "${BATS_TEST_TMPDIR}/init-home.XXXXXX")
  HOME_DIR="${TEST_ROOT}/home"
  SSH_DIR="${HOME_DIR}/.ssh"
  export TEST_ROOT HOME_DIR SSH_DIR TEST_EVENTS="${TEST_ROOT}/events"
  mkdir -p "${TEST_ROOT}/bin" "${HOME_DIR}" \
    "${HOME_DIR}/.trae/user_rules" "${HOME_DIR}/.trae-cn/user_rules" \
    "${HOME_DIR}/.vscode-server/data/Machine" \
    "${HOME_DIR}/.trae-server/data/Machine" \
    "${HOME_DIR}/.trae-cn-server/data/Machine"
  printf 'image config\n' >"${HOME_DIR}/.trae/sandbox.json"
  printf 'image settings\n' >"${HOME_DIR}/.vscode-server/data/Machine/settings.json"
  printf 'image rules\n' >"${HOME_DIR}/.trae/user_rules/workspace.md"

  # 命令桩记录初始化参数，并输出可识别的插件脚本。
  cat >"${TEST_ROOT}/bin/conda" <<'EOF'
#!/usr/bin/env bash
printf 'conda %s\n' "$*" >>"${TEST_EVENTS}"
printf '# conda plugin\n'
EOF
  cat >"${TEST_ROOT}/bin/starship" <<'EOF'
#!/usr/bin/env bash
printf 'starship %s\n' "$*" >>"${TEST_EVENTS}"
printf '# starship plugin\n'
EOF
  cat >"${TEST_ROOT}/bin/atuin" <<'EOF'
#!/usr/bin/env bash
printf 'atuin %s\n' "$*" >>"${TEST_EVENTS}"
printf '# atuin plugin\n'
EOF
  cat >"${TEST_ROOT}/bin/sudo" <<'EOF'
#!/usr/bin/env bash
printf 'sudo %s\n' "$*" >>"${TEST_EVENTS}"
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
    "${HELPER}" >"${TEST_ROOT}/helper"
  chmod +x "${TEST_ROOT}/helper"
  export PATH="${TEST_ROOT}/bin:${PATH}"
}

teardown() {
  rm -rf -- "${TEST_ROOT}"
}

@test "IDE configuration is baked into the image home" {
  local image_home="${BATS_TEST_DIRNAME}/../rootfs/home/x"

  [[ $(readlink "${image_home}/.trae-cn/sandbox.json") == "../.trae/sandbox.json" ]]
  [[ $(readlink "${image_home}/.trae-cn/traecli.toml") == "../.trae/traecli.toml" ]]
  [[ $(readlink "${image_home}/.trae-cn/user_rules/workspace.md") == "../../.trae/user_rules/workspace.md" ]]
  [[ $(readlink "${image_home}/.trae-server/data/Machine/settings.json") == "../../../.vscode-server/data/Machine/settings.json" ]]
  [[ $(readlink "${image_home}/.trae-cn-server/data/Machine/settings.json") == "../../../.vscode-server/data/Machine/settings.json" ]]
  cmp -s "${image_home}/.trae/sandbox.json" "${image_home}/.trae-cn/sandbox.json"
  cmp -s "${image_home}/.trae/traecli.toml" "${image_home}/.trae-cn/traecli.toml"
  cmp -s \
    "${image_home}/.trae/user_rules/workspace.md" \
    "${image_home}/.trae-cn/user_rules/workspace.md"
  cmp -s \
    "${image_home}/.vscode-server/data/Machine/settings.json" \
    "${image_home}/.trae-server/data/Machine/settings.json"
  cmp -s \
    "${image_home}/.vscode-server/data/Machine/settings.json" \
    "${image_home}/.trae-cn-server/data/Machine/settings.json"
}

@test "home init generates shell plugins consumed directly by zshrc" {
  run "${TEST_ROOT}/helper"

  [[ ${status} -eq 0 ]]
  [[ $(<"${HOME_DIR}/.cache/conda.plugin.zsh") == "# conda plugin" ]]
  [[ $(<"${HOME_DIR}/.cache/starship.plugin.zsh") == "# starship plugin" ]]
  [[ $(<"${HOME_DIR}/.cache/atuin.plugin.zsh") == "# atuin plugin" ]]
  grep -qx "conda shell.zsh hook" "${TEST_EVENTS}"
  grep -qx "starship init zsh" "${TEST_EVENTS}"
  grep -qx "atuin init zsh --disable-up-arrow" "${TEST_EVENTS}"

  local zshrc="${BATS_TEST_DIRNAME}/../rootfs/home/x/.zshrc"
  grep -Fqx "source \"\$XDG_CACHE_HOME/conda.plugin.zsh\"" "${zshrc}"
  grep -Fqx "source \"\$XDG_CACHE_HOME/starship.plugin.zsh\"" "${zshrc}"
  grep -Fqx "source \"\$XDG_CACHE_HOME/atuin.plugin.zsh\"" "${zshrc}"
  run ! grep -Eq 'command -v (conda|starship|atuin)' "${zshrc}"

  [[ -f ${BATS_TEST_DIRNAME}/../rootfs/etc/s6/s6-rc.d/sshd/dependencies.d/home-init ]]
}

@test "home init prepares the persistent IDE subdirectories before setup" {
  run "${TEST_ROOT}/helper"

  [[ ${status} -eq 0 ]]
  grep -qx "sudo install -d -o 5230 -g 5230 -m 0700 -- ${HOME_DIR}/.vscode-server/bin ${HOME_DIR}/.vscode-server/extensions ${HOME_DIR}/.trae/bin ${HOME_DIR}/.trae/extensions ${HOME_DIR}/.trae-cn/bin ${HOME_DIR}/.trae-cn/extensions ${HOME_DIR}/.trae-server/bin ${HOME_DIR}/.trae-server/extensions ${HOME_DIR}/.trae-cn-server/bin ${HOME_DIR}/.trae-cn-server/extensions" "${TEST_EVENTS}"
  grep -qx "seeded" "${TEST_EVENTS}"
  # Directory preparation must precede the seed/setup steps.
  local prepare_line seed_line
  prepare_line=$(grep -n "^sudo install " "${TEST_EVENTS}" | cut -d: -f1)
  seed_line=$(grep -nx "seeded" "${TEST_EVENTS}" | cut -d: -f1)
  [[ ${seed_line} -gt ${prepare_line} ]]
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
  [[ $(<"${HOME_DIR}/.trae/sandbox.json") == "image config" ]]
  [[ $(<"${HOME_DIR}/.vscode-server/data/Machine/settings.json") == "image settings" ]]
  [[ $(<"${HOME_DIR}/.trae/user_rules/workspace.md") == "image rules" ]]

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
