#!/usr/bin/env bash
# Provision the macOS host and install Codespace-managed home configuration.
# Usage: install.sh [--with-atuin-server]
# Requires Bash 3.2 or newer, curl, sudo, and Apple Silicon macOS.

link_home_path() {
  local source="$1/$2"
  local destination="$HOME/$2"
  local mode="${3:-}"

  if [[ ! -e "$source" ]]; then
    printf 'error: source does not exist: %s\n' "$source" >&2
    exit 1
  fi
  if [[ -n "$mode" ]]; then
    chmod "$mode" "$source"
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

copy_home_path() {
  local source="$1/$2"
  local destination="$HOME/$2"
  local mode="$3"

  if [[ ! -f "$source" ]]; then
    printf 'error: source does not exist: %s\n' "$source" >&2
    exit 1
  fi

  mkdir -p "$(dirname "$destination")"
  if [[ -e "$destination" || -L "$destination" ]]; then
    rm -rf "$destination"
  fi
  install -m "$mode" "$source" "$destination"
  printf 'installed %s\n' "$destination"
}

install_homebrew() {
  local script_dir="$1"
  local temp_dir="$2"

  if [[ ! -x /opt/homebrew/bin/brew ]]; then
    local installer="$temp_dir/homebrew-install.sh"
    curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh \
      -o "$installer"
    NONINTERACTIVE=1 /bin/bash "$installer"
  fi

  export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$PATH"
  /opt/homebrew/bin/brew bundle \
    --force \
    --file "$script_dir/Brewfile" \
    --verbose
  /opt/homebrew/bin/brew cleanup --prune=all
}

install_binman() {
  local script_dir="$1"
  local temp_dir="$2"
  local current_user current_group installer
  current_user="$(id -un)"
  current_group="$(id -gn)"
  installer="$temp_dir/binman-install.sh"

  if [[ ! -d /opt/bm ]]; then
    sudo install -d -o "$current_user" -g "$current_group" /opt/bm
  fi

  mkdir -p /opt/bm/bin
  curl -fsSL \
    https://raw.githubusercontent.com/curoky/standalone-binaries/refs/heads/master/cmd/binman/install.sh \
    -o "$installer"
  /bin/bash "$installer" --prefix /opt/bm/bin

  /opt/bm/bin/bm sync --prefix /opt/bm "$script_dir/binman.yaml"
  ln -sfn /opt/bm/bin/bazelisk /opt/bm/bin/bazel
}

install_home_config() {
  local macos_home="$1"

  install -d -m 0700 "$HOME/.ssh" "$HOME/.ssh/codespace" \
    "$HOME/.ssh/codespace/known_hosts"
  link_home_path "$macos_home" ".gitconfig" 0600
  link_home_path "$macos_home" ".config/git/user.gitconfig" 0600
  link_home_path "$macos_home" ".config/git/ignore"
  link_home_path "$macos_home" ".ssh/config" 0600
  link_home_path "$macos_home" ".ssh/codespace/config" 0600
  link_home_path "$macos_home" ".ssh/codespace/login_key" 0600
  link_home_path "$macos_home" ".ssh/codespace/known_hosts/codespace" 0600
  link_home_path "$macos_home" ".ssh/codespace/proxy" 0700

  link_home_path "$macos_home" ".zshrc"
  link_home_path "$macos_home" ".config/zsh/aliases.zsh"
  link_home_path "$macos_home" ".config/zsh/functions.zsh"
  link_home_path "$macos_home" ".config/zsh/git.zsh"

  link_home_path "$macos_home" ".config/atuin/config.toml"
  link_home_path "$macos_home" ".config/bat/config"
  link_home_path "$macos_home" ".config/nixpkgs/config.nix"
  link_home_path "$macos_home" ".config/starship.toml"
  link_home_path "$macos_home" ".config/tmux/tmux.conf"
  link_home_path "$macos_home" ".vimrc"

  link_home_path "$macos_home" ".config/mpv/mpv.conf"
  link_home_path "$macos_home" ".snipaste/config.ini"
  link_home_path "$macos_home" ".warp/settings.toml"

  local editor
  for editor in Code Trae "Trae CN"; do
    link_home_path "$macos_home" "Library/Application Support/$editor/User/settings.json"
    link_home_path "$macos_home" "Library/Application Support/$editor/User/keybindings.json"
    link_home_path "$macos_home" "Library/Application Support/$editor/User/snippets"
  done

  copy_home_path "$macos_home" ".trae/sandbox.json" 0600
  copy_home_path "$macos_home" ".trae/traecli.toml" 0600
  copy_home_path "$macos_home" ".trae-cn/sandbox.json" 0600
  copy_home_path "$macos_home" ".trae-cn/traecli.toml" 0600
}

load_launch_agent() {
  local macos_home="$1"
  local label="$2"
  local relative_path="Library/LaunchAgents/${label}.plist"
  local domain
  domain="gui/$(id -u)"

  link_home_path "$macos_home" "$relative_path"
  launchctl bootout "$domain/$label" >/dev/null 2>&1 || true
  launchctl bootstrap "$domain" "$HOME/$relative_path"
  launchctl kickstart -k "$domain/$label"
}

main() {
  set -euo pipefail

  local with_atuin_server=false
  while (($# > 0)); do
    case "$1" in
      --with-atuin-server)
        with_atuin_server=true
        ;;
      -h | --help)
        printf 'usage: %s [--with-atuin-server]\n' "${0##*/}"
        return 0
        ;;
      *)
        printf 'error: unsupported argument: %s\n' "$1" >&2
        return 2
        ;;
    esac
    shift
  done

  local script_dir macos_home
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
  macos_home="$script_dir/rootfs/Users/x"
  # Keep this global so EXIT can read it after a Bash 3.2 error.
  temp_dir="$(mktemp -d)"
  trap 'rm -rf "$temp_dir"' EXIT

  install_homebrew "$script_dir" "$temp_dir"
  install_binman "$script_dir" "$temp_dir"
  export PATH="/opt/bm/bin:$PATH"
  install_home_config "$macos_home"
  swift "$script_dir/scripts/set-default-apps.swift"
  load_launch_agent "$macos_home" sh.atuin.daemon
  if [[ "$with_atuin_server" == true ]]; then
    load_launch_agent "$macos_home" sh.atuin.server
  fi

  rm -rf "$temp_dir"
  trap - EXIT
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
