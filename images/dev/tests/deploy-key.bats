#!/usr/bin/env bats

setup_file() {
  bats_require_minimum_version 1.5.0
  HELPER="${BATS_TEST_DIRNAME}/../rootfs/opt/codespace/bin/deploy-key"
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
  TEST_ROOT=$(mktemp -d "${BATS_TEST_TMPDIR}/deploy-key.XXXXXX")
  export TEST_ROOT
}

teardown() {
  rm -rf -- "${TEST_ROOT}"
}

@test "deploy key remains inside the workspace container" {
  local home="${TEST_ROOT}/home"
  mkdir -p "${home}"

  run --separate-stderr env HOME="${home}" "${HELPER_BASH}" "${HELPER}"

  [[ ${status} -eq 0 ]]
  [[ -z ${output} ]]
  [[ -f ${home}/.ssh/repo_id_ed25519 ]]
  [[ -f ${home}/.ssh/repo_id_ed25519.pub ]]
  run ssh-keygen -l -f "${home}/.ssh/repo_id_ed25519.pub"
  [[ ${status} -eq 0 ]]
  local mode
  mode=$(stat -f %Lp "${home}/.ssh/repo_id_ed25519" 2>/dev/null ||
    stat -c %a "${home}/.ssh/repo_id_ed25519")
  [[ ${mode} == 600 ]]

  local first_public_key
  first_public_key=$(<"${home}/.ssh/repo_id_ed25519.pub")
  run --separate-stderr env HOME="${home}" "${HELPER_BASH}" "${HELPER}"
  [[ ${status} -eq 0 ]]
  [[ -z ${output} ]]
  [[ $(<"${home}/.ssh/repo_id_ed25519.pub") == "${first_public_key}" ]]
}

@test "deploy key rejects arguments" {
  run --separate-stderr "${HELPER_BASH}" "${HELPER}" unexpected

  [[ ${status} -eq 2 ]]
  [[ ${stderr} == *"usage: deploy-key"* ]]
}
