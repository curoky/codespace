#!/usr/bin/env bash

set -euo pipefail

process_matches() {
  local pid="$1"
  kill -0 "$pid" 2>/dev/null &&
    ps -p "$pid" -o command= 2>/dev/null | grep -q '[c]odespace serve'
}

process_alive() {
  kill -0 "$1" 2>/dev/null
}

listener_pid() {
  lsof -nP -tiTCP:8003 -sTCP:LISTEN 2>/dev/null | sed -n '1p'
}

stop_process() {
  local pid="$1" attempt=0
  kill -TERM "$pid" 2>/dev/null || return 0
  while ((attempt < 30)); do
    process_alive "$pid" || return 0
    sleep 0.1
    ((attempt += 1))
  done
  kill -KILL "$pid" 2>/dev/null || true
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
  command -v lsof >/dev/null 2>&1 || {
    printf 'error: lsof is required\n' >&2
    return 1
  }

  local script_dir repo_root state_dir log_file pid_file previous_pid active_pid executable attempt
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
  repo_root="$(cd "$script_dir/.." && pwd -P)"
  state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/codespace"
  log_file="$state_dir/control-plane.log"
  pid_file="$state_dir/control-plane.pid"
  executable="$repo_root/.venv/bin/codespace"
  mkdir -p "$state_dir"

  uv sync --directory "$repo_root" --quiet

  if [[ -r "$pid_file" ]]; then
    read -r previous_pid <"$pid_file"
    if [[ "$previous_pid" =~ ^[0-9]+$ ]] && process_matches "$previous_pid"; then
      printf 'stopping previous Codespace control plane (pid %s)\n' "$previous_pid"
      stop_process "$previous_pid"
    fi
    rm -f "$pid_file"
  fi

  active_pid="$(listener_pid || true)"
  if [[ -n "$active_pid" ]]; then
    if ! process_matches "$active_pid"; then
      printf 'error: port 8003 is already used by pid %s\n' "$active_pid" >&2
      return 1
    fi
    printf 'stopping untracked Codespace control plane (pid %s)\n' "$active_pid"
    stop_process "$active_pid"
  fi

  {
    printf '===== %s starting Codespace =====\n' "$(date '+%Y-%m-%d %H:%M:%S')"
    printf 'repo_root=%s\n' "$repo_root"
    printf 'url=http://127.0.0.1:8003\n'
  } >"$log_file"

  cd "$repo_root"
  nohup "$executable" serve \
    >>"$log_file" 2>&1 </dev/null &
  local control_plane_pid=$!
  printf '%s\n' "$control_plane_pid" >"$pid_file"

  attempt=0
  while ((attempt < 50)); do
    if ! process_alive "$control_plane_pid"; then
      break
    fi
    active_pid="$(listener_pid || true)"
    if [[ "$active_pid" == "$control_plane_pid" ]]; then
      break
    fi
    sleep 0.1
    ((attempt += 1))
  done
  active_pid="$(listener_pid || true)"
  if ! process_alive "$control_plane_pid" || [[ "$active_pid" != "$control_plane_pid" ]]; then
    process_alive "$control_plane_pid" && stop_process "$control_plane_pid"
    rm -f "$pid_file"
    printf 'error: Codespace control plane failed to start; see %s\n' "$log_file" >&2
    return 1
  fi

  printf 'Codespace control plane started (pid %s)\n' "$control_plane_pid"
  printf 'url: http://127.0.0.1:8003\n'
  printf 'log: %s\n' "$log_file"
}

main "$@"
