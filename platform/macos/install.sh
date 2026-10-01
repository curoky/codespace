#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
macos_home="$script_dir/rootfs/Users/x"
export PATH="/opt/bm/bin:$PATH"

link_home_path() {
  local source="$macos_home/$1"
  local destination="$HOME/$1"

  if [[ ! -e "$source" ]]; then
    printf 'error: source does not exist: %s\n' "$source" >&2
    exit 1
  fi
  if [[ -f "$source" ]]; then
    chmod 0600 "$source"
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
  local source="$macos_home/$1"
  local destination="$HOME/$1"

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

install_homebrew() {
  if [[ ! -x /opt/homebrew/bin/brew ]]; then
    local installer="/tmp/homebrew-install.sh"
    curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh \
      -o "$installer"
    NONINTERACTIVE=1 /bin/bash "$installer"
  fi

  export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$PATH"
  /opt/homebrew/bin/brew bundle \
    --force \
    --force-cleanup \
    --file "$script_dir/Brewfile" \
    --verbose
  /opt/homebrew/bin/brew cleanup --prune=all
}

install_binman() {
  local current_user current_group installer
  current_user="$(id -un)"
  current_group="$(id -gn)"
  installer="/tmp/binman-install.sh"

  if [[ ! -d /opt/bm ]]; then
    sudo install -d -o "$current_user" -g "$current_group" /opt/bm
  fi

  curl -fsSL \
    https://raw.githubusercontent.com/curoky/standalone-binaries/refs/heads/master/cmd/binman/install.sh \
    -o "$installer"
  /bin/bash "$installer" --prefix /opt/bm

  /opt/bm/bin/bm --prefix /opt/bm install --file "$script_dir/binman.yaml"
  ln -sfn /opt/bm/bin/bazelisk /opt/bm/bin/bazel
}

install_home_config() {
  install -d -m 0700 "$HOME/.ssh" "$HOME/.ssh/codespace" \
    "$HOME/.ssh/codespace/known_hosts" "$HOME/.ssh/codespace/workspaces"
  link_home_path ".gitconfig"
  link_home_path ".config/git/user.gitconfig"
  link_home_path ".config/git/ignore"
  link_home_path ".ssh/config"
  link_home_path ".ssh/codespace/config"
  link_home_path ".ssh/codespace/workspace_login_key_ed25519"
  link_home_path ".ssh/codespace/known_hosts/codespace"

  link_home_path ".zshrc"
  link_home_path ".config/zsh/aliases.zsh"
  link_home_path ".config/zsh/functions.zsh"
  link_home_path ".config/zsh/git.zsh"

  link_home_path ".config/atuin/config.toml"
  link_home_path ".config/bat/config"
  link_home_path ".config/nixpkgs/config.nix"
  link_home_path ".config/starship.toml"
  link_home_path ".config/tmux/tmux.conf"
  link_home_path ".vimrc"

  link_home_path ".config/mpv/mpv.conf"
  link_home_path ".snipaste/config.ini"
  link_home_path ".warp/settings.toml"

  local editor
  for editor in Code Trae "Trae CN"; do
    link_home_path "Library/Application Support/$editor/User/settings.json"
    link_home_path "Library/Application Support/$editor/User/keybindings.json"
    link_home_path "Library/Application Support/$editor/User/snippets"
  done

  copy_home_path ".trae/sandbox.json"
  copy_home_path ".trae/traecli.toml"
  copy_home_path ".trae-cn/sandbox.json"
  copy_home_path ".trae-cn/traecli.toml"
}

load_launch_agent() {
  local label="$1"
  local relative_path="Library/LaunchAgents/${label}.plist"
  local domain
  domain="gui/$(id -u)"

  copy_home_path "$relative_path"
  launchctl bootout "$domain/$label" >/dev/null 2>&1 || true
  launchctl bootstrap "$domain" "$HOME/$relative_path"
  launchctl kickstart -k "$domain/$label"
}

install_homebrew
install_binman
install_home_config
swift "$script_dir/scripts/set-default-apps.swift"
load_launch_agent sh.atuin.daemon
# load_launch_agent sh.atuin.server
