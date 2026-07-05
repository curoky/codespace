#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../.." && pwd)"
run_dir="$(pwd)"
log_file="${run_dir}/codespace-client.log"

host="${CODESPACE_WEB_HOST:-127.0.0.1}"
port="${CODESPACE_WEB_PORT:-8765}"

server_process_exists() {
  pgrep -f "uv run python -m codespace.client" >/dev/null 2>&1 \
    || pgrep -f "python -m codespace.client" >/dev/null 2>&1
}

stop_server_processes() {
  local signal="$1"
  pkill -"${signal}" -f "uv run python -m codespace.client" 2>/dev/null || true
  pkill -"${signal}" -f "python -m codespace.client" 2>/dev/null || true
}

if server_process_exists; then
  echo "stopping previous codespace client web server"
  stop_server_processes TERM
  for _ in {1..30}; do
    server_process_exists || break
    sleep 0.1
  done
  if server_process_exists; then
    echo "previous server did not stop gracefully, killing"
    stop_server_processes KILL
  fi
fi

{
  echo "===== $(date '+%Y-%m-%d %H:%M:%S') starting codespace client web server ====="
  echo "cwd=${run_dir}"
  echo "repo_root=${repo_root}"
  echo "url=http://${host}:${port}"
} >>"${log_file}"

nohup bash -c 'cd "$1" && exec uv run python -m codespace.client' _ "${repo_root}" \
  >>"${log_file}" 2>&1 </dev/null &

echo "codespace client web server started"
echo "url: http://${host}:${port}"
echo "log: ${log_file}"
