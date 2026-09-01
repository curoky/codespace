#!/usr/bin/env bats

setup_file() {
  bats_require_minimum_version 1.5.0
  HELPER="${BATS_TEST_DIRNAME}/../rootfs/opt/codespace/bin/codespace-workspace-state"
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
  TEST_ROOT=$(mktemp -d "${BATS_TEST_TMPDIR}/codespace-workspace-state.XXXXXX")
  export TEST_ROOT
}

teardown() {
  rm -rf -- "${TEST_ROOT}"
}

helper() {
  "${HELPER_BASH}" "${HELPER}" "$@"
}

init_repository() {
  local target=$1
  git init -q "${target}"
  git -C "${target}" config user.name "Codespace Test"
  git -C "${target}" config user.email "codespace@example.com"
}

@test "state reports a missing checkout as clean" {
  run --separate-stderr helper "${TEST_ROOT}/missing"

  [[ ${status} -eq 0 ]]
  jq -e '.unpushed == false and .uncommitted == false and .detail == []' <<<"${output}"
}

@test "state reports an empty repository as clean without a bootstrap marker" {
  local checkout="${TEST_ROOT}/workspace/repository"
  init_repository "${checkout}"

  run --separate-stderr helper "${checkout}"

  [[ ${status} -eq 0 ]]
  jq -e '.unpushed == false and .uncommitted == false and .detail == []' <<<"${output}"
}

@test "state reports uncommitted and unpushed work" {
  local checkout="${TEST_ROOT}/workspace/repository"
  init_repository "${checkout}"
  printf 'initial\n' >"${checkout}/README.md"
  git -C "${checkout}" add README.md
  git -C "${checkout}" commit -qm "initial"
  printf 'changed\n' >>"${checkout}/README.md"

  run --separate-stderr helper "${checkout}"

  [[ ${status} -eq 0 ]]
  jq -e '.unpushed == true and .uncommitted == true and (.detail | length) == 2' <<<"${output}"
}

@test "state caps detail at twenty lines" {
  local checkout="${TEST_ROOT}/workspace/repository"
  init_repository "${checkout}"
  local index
  for index in {1..25}; do
    printf '%s\n' "${index}" >"${checkout}/file-${index}.txt"
  done

  run --separate-stderr helper "${checkout}"

  [[ ${status} -eq 0 ]]
  jq -e '.uncommitted == true and (.detail | length) == 20' <<<"${output}"
}

@test "state rejects invalid argument counts" {
  run --separate-stderr helper

  [[ ${status} -eq 2 ]]
  [[ ${stderr} == *"usage: codespace-workspace-state"* ]]
}
