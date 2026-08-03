#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../.." && pwd)"
log_file="${repo_root}/codespace-client.log"
uv_bin="$(command -v uv)"
readonly uv_bin
readonly process_pattern='python -m codespace.client'

server_process_exists() {
  pgrep -f "${process_pattern}" >/dev/null 2>&1
}

stop_server_processes() {
  local signal="$1"
  pkill -"${signal}" -f "${process_pattern}" 2>/dev/null || true
}

if server_process_exists; then
  echo "stopping previous codespace control plane"
  stop_server_processes TERM
  for _ in {1..30}; do
    server_process_exists || break
    sleep 0.1
  done
  if server_process_exists; then
    echo "previous control plane did not stop gracefully, killing"
    stop_server_processes KILL
  fi
fi

rm -rf "${log_file}"
{
  echo "===== $(date '+%Y-%m-%d %H:%M:%S') starting codespace ====="
  echo "repo_root=${repo_root}"
  echo "url=http://127.0.0.1:8003"
} >>"${log_file}"

nohup "${uv_bin}" run --directory "${repo_root}" python -m codespace.client \
  >>"${log_file}" 2>&1 </dev/null &

echo "codespace control plane started"
echo "url: http://127.0.0.1:8003"
echo "log: ${log_file}"
