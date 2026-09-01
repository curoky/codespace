#!/usr/bin/env bats

setup_file() {
  bats_require_minimum_version 1.5.0
  HELPER="${BATS_TEST_DIRNAME}/../rootfs/opt/codespace/bin/codespace-workspace-open-path"
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
  TEST_ROOT=$(mktemp -d "${BATS_TEST_TMPDIR}/codespace-workspace-open-path.XXXXXX")
  export TEST_ROOT
}

teardown() {
  rm -rf -- "${TEST_ROOT}"
}

@test "open path creates the complete directory tree" {
  local open_path="${TEST_ROOT}/workspace/nested"

  run --separate-stderr "${HELPER_BASH}" "${HELPER}" "${open_path}"

  [[ ${status} -eq 0 ]]
  [[ -z ${output} ]]
  [[ -z ${stderr} ]]
  [[ -d ${open_path} ]]
}

@test "open path rejects invalid argument counts" {
  run --separate-stderr "${HELPER_BASH}" "${HELPER}"

  [[ ${status} -eq 2 ]]
  [[ ${stderr} == *"usage: codespace-workspace-open-path"* ]]
}
