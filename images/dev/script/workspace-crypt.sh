#!/usr/bin/env bash
# gocryptfs 加密 /workspace：加密类 project 由控制面把 host 实例目录 bind mount 到
# 密文根 /workspace.enc，并注入口令 env WORKSPACE_CRYPT_KEY（来源同 atuin_db_uri：
# podman secret + sync_secrets）。本 oneshot 据该 env 是否存在自适应：
#   - 存在：boot 时 init（首次）并把明文挂到 /workspace；
#   - 不存在：非加密 project，host 目录已直接 bind 到 /workspace 明文，直接跳过。
# sshd/home-init/WebDAV 均依赖本 oneshot 完成后才起，两种模式下看到的都是明文 /workspace。

set -euo pipefail

CIPHER_DIR=/workspace.enc
PLAIN_DIR=/workspace

# 非加密 project 不注入口令：/workspace 已是 host bind 明文，无需 gocryptfs。
if [[ -z "${WORKSPACE_CRYPT_KEY:-}" ]]; then
  echo "WORKSPACE_CRYPT_KEY unset; workspace encryption disabled, using plaintext ${PLAIN_DIR}"
  exit 0
fi

# 已挂载则幂等返回（同一 container stop/start 后重跑）。用 /proc/mounts 判断，
# 不依赖 util-linux 的 mountpoint。
if grep -q " ${PLAIN_DIR} fuse.gocryptfs " /proc/mounts; then
  echo "gocryptfs already mounted at ${PLAIN_DIR}"
  exit 0
fi

# 首次：密文根为空时初始化 gocryptfs.conf。-extpass 从 env 读口令，避免口令落盘。
if [[ ! -e "${CIPHER_DIR}/gocryptfs.conf" ]]; then
  gocryptfs -init -extpass 'echo "${WORKSPACE_CRYPT_KEY}"' "${CIPHER_DIR}"
fi

# -allow_other 让 root（sshd 会话）与其他用户能穿越以 x 身份挂载的明文树；
# 需 /etc/fuse.conf 里 user_allow_other（镜像已烤入）。
gocryptfs -extpass 'echo "${WORKSPACE_CRYPT_KEY}"' -allow_other "${CIPHER_DIR}" "${PLAIN_DIR}"
