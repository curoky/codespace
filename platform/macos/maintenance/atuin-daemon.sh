#!/usr/bin/env bash
set -euo pipefail

macos_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
source_plist="$macos_dir/rootfs/Users/x/Library/LaunchAgents/sh.atuin.daemon.plist"
target_plist="$HOME/Library/LaunchAgents/sh.atuin.daemon.plist"
domain="gui/$(id -u)"

install -d "$HOME/Library/LaunchAgents"
install -m 0600 "$source_plist" "$target_plist"
launchctl bootout "$domain/sh.atuin.daemon" >/dev/null 2>&1 || true

for _ in {1..20}; do
  if ! launchctl print "$domain/sh.atuin.daemon" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done

launchctl bootstrap "$domain" "$target_plist"
launchctl kickstart -k "$domain/sh.atuin.daemon"

for _ in {1..40}; do
  if launchctl print "$domain/sh.atuin.daemon" >/dev/null 2>&1 &&
    [[ -S "$HOME/.local/share/atuin/atuin.sock" ]]; then
    exit 0
  fi
  sleep 0.25
done

launchctl print "$domain/sh.atuin.daemon" >&2 || true
tail -n 100 /tmp/atuin.daemon.log >&2 || true
exit 1
