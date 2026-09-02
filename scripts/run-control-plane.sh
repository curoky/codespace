#!/usr/bin/env bash
# Restart the local Codespace control plane in the background.
# Usage: run-control-plane.sh
# Requires Bash 3.2 or newer, uv, and standard ps/kill utilities.

set -euo pipefail

process_matches() {
  local pid="$1"
  kill -0 "$pid" 2>/dev/null &&
    ps -p "$pid" -o command= 2>/dev/null | grep -q '[c]odespace serve'
}

main() {
  if ((BASH_VERSINFO[0] < 3)); then
    printf 'error: Bash 3.2 or newer is required\n' >&2
    return 2
  fi
  if (($# != 0)); then
    printf 'usage: %s\n' "${0##*/}" >&2
    return 2
  fi
  command -v uv >/dev/null 2>&1 || {
    printf 'error: uv is required\n' >&2
    return 1
  }

  local script_dir repo_root state_dir log_file pid_file previous_pid
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
  repo_root="$(cd "$script_dir/.." && pwd -P)"
  state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/codespace"
  log_file="$state_dir/control-plane.log"
  pid_file="$state_dir/control-plane.pid"
  mkdir -p "$state_dir"

  if [[ -r "$pid_file" ]]; then
    read -r previous_pid <"$pid_file"
    if [[ "$previous_pid" =~ ^[0-9]+$ ]] && process_matches "$previous_pid"; then
      printf 'stopping previous Codespace control plane (pid %s)\n' "$previous_pid"
      kill -TERM "$previous_pid"
      for _ in {1..30}; do
        process_matches "$previous_pid" || break
        sleep 0.1
      done
      if process_matches "$previous_pid"; then
        kill -KILL "$previous_pid"
      fi
    fi
    rm -f "$pid_file"
  fi

  {
    printf '===== %s starting Codespace =====\n' "$(date '+%Y-%m-%d %H:%M:%S')"
    printf 'repo_root=%s\n' "$repo_root"
    printf 'url=http://127.0.0.1:8003\n'
  } >"$log_file"

  nohup uv run --directory "$repo_root" codespace serve \
    >>"$log_file" 2>&1 </dev/null &
  local control_plane_pid=$!
  printf '%s\n' "$control_plane_pid" >"$pid_file"

  sleep 0.2
  if ! process_matches "$control_plane_pid"; then
    rm -f "$pid_file"
    printf 'error: Codespace control plane failed to start; see %s\n' "$log_file" >&2
    return 1
  fi

  printf 'Codespace control plane started (pid %s)\n' "$control_plane_pid"
  printf 'url: http://127.0.0.1:8003\n'
  printf 'log: %s\n' "$log_file"
}

main "$@"
