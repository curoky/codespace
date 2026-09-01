#!/usr/bin/env bats

setup_file() {
  bats_require_minimum_version 1.5.0
  HELPER="${BATS_TEST_DIRNAME}/../rootfs/opt/codespace/bin/workspace-crypt"
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

@test "workspace crypt skips plaintext workspaces" {
  run --separate-stderr env -u WORKSPACE_CRYPT_KEY "${HELPER_BASH}" "${HELPER}"

  [[ ${status} -eq 0 ]]
  [[ ${output} == *"workspace encryption disabled"* ]]
  [[ -z ${stderr} ]]
}
