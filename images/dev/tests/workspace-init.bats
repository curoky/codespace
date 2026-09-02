#!/usr/bin/env bats

setup_file() {
  bats_require_minimum_version 1.5.0
  HELPER="${BATS_TEST_DIRNAME}/../rootfs/opt/codespace/bin/workspace-init"
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
  # 对象脚本以 sudo chown 归属数据 mount; 测试环境用 no-op sudo 桩屏蔽, 只验证明文分支.
  STUB_BIN=$(mktemp -d "${BATS_TEST_TMPDIR}/stub.XXXXXX")
  cat >"${STUB_BIN}/sudo" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  chmod +x "${STUB_BIN}/sudo"
  export PATH="${STUB_BIN}:${PATH}"
}

# 明文场景(WORKSPACE_CRYPT_KEY 未设)直接跳过挂载.
@test "workspace init skips plaintext workspaces" {
  run --separate-stderr env -u WORKSPACE_CRYPT_KEY PATH="${PATH}" "${HELPER_BASH}" "${HELPER}"

  [[ ${status} -eq 0 ]]
  [[ ${output} == *"workspace encryption disabled"* ]]
  [[ -z ${stderr} ]]
}
