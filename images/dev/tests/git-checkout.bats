#!/usr/bin/env bats

setup_file() {
  bats_require_minimum_version 1.5.0
  HELPER="${BATS_TEST_DIRNAME}/../rootfs/opt/codespace/bin/git-checkout"
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
  TEST_ROOT=$(mktemp -d "${BATS_TEST_TMPDIR}/git-checkout.XXXXXX")
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

create_origin() {
  local origin=$1
  local seed="${TEST_ROOT}/seed"
  init_repository "${seed}"
  printf 'initial\n' >"${seed}/README.md"
  git -C "${seed}" add README.md
  git -C "${seed}" commit -qm "initial"
  git clone -q --bare "${seed}" "${origin}"
}

@test "checkout clones a repository" {
  local origin="${TEST_ROOT}/origin.git"
  local checkout="${TEST_ROOT}/workspace/repository"
  create_origin "${origin}"

  run --separate-stderr helper "file://${origin}" "${checkout}"

  [[ ${status} -eq 0 ]]
  [[ -z ${output} ]]
  [[ -d ${checkout}/.git ]]
}

@test "checkout reuses an intact repository" {
  local origin="${TEST_ROOT}/origin.git"
  local checkout="${TEST_ROOT}/workspace/repository"
  create_origin "${origin}"
  helper "file://${origin}" "${checkout}"
  printf 'local\n' >"${checkout}/local.txt"

  run --separate-stderr helper "file://${origin}" "${checkout}"

  [[ ${status} -eq 0 ]]
  [[ -f ${checkout}/local.txt ]]
}

@test "checkout marks an empty repository" {
  local origin="${TEST_ROOT}/empty.git"
  local checkout="${TEST_ROOT}/workspace/empty"
  git init -q --bare "${origin}"

  run helper "file://${origin}" "${checkout}"

  [[ ${status} -eq 0 ]]
  [[ -f ${checkout}/.git/codespace-empty-repository ]]
}

@test "checkout refuses to replace a non-checkout target" {
  local origin="${TEST_ROOT}/origin.git"
  local checkout="${TEST_ROOT}/workspace/repository"
  create_origin "${origin}"
  mkdir -p "${checkout}"
  printf 'keep\n' >"${checkout}/local.txt"

  run --separate-stderr helper "file://${origin}" "${checkout}"

  [[ ${status} -eq 1 ]]
  [[ ${stderr} == *"exists but is not a checkout"* ]]
  [[ -f ${checkout}/local.txt ]]
}

@test "checkout rejects invalid argument counts" {
  run --separate-stderr helper only-one

  [[ ${status} -eq 2 ]]
  [[ ${stderr} == *"usage: git-checkout"* ]]
}
