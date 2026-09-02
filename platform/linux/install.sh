#!/usr/bin/env bash
# Install Codespace-managed dotfiles for a Linux host.
# Usage: install.sh
# Requires Bash 3.2 or newer and standard core utilities.

set -euo pipefail

link_path() {
  local source="$1"
  local destination="$2"

  if [[ ! -e "$source" ]]; then
    printf 'error: source does not exist: %s\n' "$source" >&2
    exit 1
  fi
  if [[ -L "$destination" && "$(readlink "$destination")" == "$source" ]]; then
    return
  fi

  mkdir -p "$(dirname "$destination")"
  if [[ -e "$destination" || -L "$destination" ]]; then
    rm -rf "$destination"
  fi
  ln -s "$source" "$destination"
  printf 'linked %s -> %s\n' "$destination" "$source"
}

copy_private() {
  local source="$1"
  local destination="$2"

  if [[ ! -f "$source" ]]; then
    printf 'error: source does not exist: %s\n' "$source" >&2
    exit 1
  fi

  mkdir -p "$(dirname "$destination")"
  if [[ -e "$destination" || -L "$destination" ]]; then
    rm -rf "$destination"
  fi
  install -m 0600 "$source" "$destination"
  printf 'installed %s\n' "$destination"
}

main() {
  if ((BASH_VERSINFO[0] < 3)); then
    printf 'error: Bash 3.2 or newer is required\n' >&2
    return 2
  fi
  if (($# == 1)) && [[ "$1" == -h || "$1" == --help ]]; then
    printf 'usage: %s\n' "${0##*/}"
    return 0
  fi
  if (($# != 0)); then
    printf 'usage: %s\n' "${0##*/}" >&2
    return 2
  fi
  if [[ "$(uname -s)" != Linux ]]; then
    printf 'error: this installer only supports Linux\n' >&2
    return 1
  fi

  local script_dir repo_root dotfiles
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
  repo_root="$(cd "$script_dir/../.." && pwd -P)"
  dotfiles="$repo_root/dotfiles"

  link_path "$dotfiles/bin/eza-wrapper" "$HOME/.local/bin/eza-wrapper"

  link_path "$dotfiles/vscode/remote/settings.json" "$HOME/.vscode-server/data/Machine/settings.json"
  link_path "$dotfiles/vscode/remote/settings.json" "$HOME/.trae-server/data/Machine/settings.json"
  link_path "$dotfiles/vscode/remote/settings.json" "$HOME/.trae-cn-server/data/Machine/settings.json"

  copy_private "$dotfiles/trae/sandbox.json" "$HOME/.trae/sandbox.json"
  copy_private "$dotfiles/trae/traecli.toml" "$HOME/.trae/traecli.toml"
  copy_private "$dotfiles/trae/sandbox.json" "$HOME/.trae-cn/sandbox.json"
  copy_private "$dotfiles/trae/traecli.toml" "$HOME/.trae-cn/traecli.toml"
}

main "$@"
