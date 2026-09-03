#!/usr/bin/env bash
# Provision the macOS host and install Codespace-managed dotfiles.
# Usage: install.sh [--with-atuin-server]
# Requires Bash 3.2 or newer, curl, sudo, and Apple Silicon macOS.

set -euo pipefail

TEMP_DIR=""

cleanup() {
  if [[ -n "$TEMP_DIR" ]]; then
    rm -rf "$TEMP_DIR"
  fi
}

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

copy_path() {
  local source="$1"
  local destination="$2"
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
    --cleanup \
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

install_dotfiles() {
  local dotfiles="$1"
  local script_dir="$2"
  local workspace_home="$3"

  copy_path "$dotfiles/git/macos.gitconfig" "$HOME/.gitconfig" 0600
  copy_path "$dotfiles/git/user.gitconfig" "$HOME/.config/git/user.gitconfig" 0600
  link_path "$dotfiles/git/ignore" "$HOME/.config/git/ignore"
  copy_path "$dotfiles/ssh/macos.config" "$HOME/.ssh/config" 0600

  link_path "$dotfiles/zsh/macos.zshrc" "$HOME/.zshrc"
  link_path "$workspace_home/.config/zsh/environment.zsh" "$HOME/.config/zsh/environment.zsh"
  link_path "$workspace_home/.config/zsh/paths.zsh" "$HOME/.config/zsh/paths.zsh"
  link_path "$workspace_home/.config/zsh/aliases.zsh" "$HOME/.config/zsh/aliases.zsh"
  link_path "$workspace_home/.config/zsh/functions.zsh" "$HOME/.config/zsh/functions.zsh"
  link_path "$workspace_home/.config/zsh/git.zsh" "$HOME/.config/zsh/git.zsh"

  link_path "$workspace_home/.config/atuin/config.toml" "$HOME/.config/atuin/config.toml"
  link_path "$workspace_home/.config/bat/config" "$HOME/.config/bat/config"
  link_path "$workspace_home/.config/conda/condarc" "$HOME/.config/conda/condarc"
  link_path "$workspace_home/.config/nixpkgs/config.nix" "$HOME/.config/nixpkgs/config.nix"
  link_path "$workspace_home/.config/starship.toml" "$HOME/.config/starship.toml"
  link_path "$workspace_home/.config/tmux/tmux.conf" "$HOME/.config/tmux/tmux.conf"
  link_path "$workspace_home/.vimrc" "$HOME/.vimrc"

  link_path "$dotfiles/mpv/mpv.conf" "$HOME/.config/mpv/mpv.conf"
  link_path "$dotfiles/snipaste/config.ini" "$HOME/.snipaste/config.ini"

  local editor_root
  for editor_root in \
    "$HOME/Library/Application Support/Code/User" \
    "$HOME/Library/Application Support/Trae/User" \
    "$HOME/Library/Application Support/Trae CN/User"; do
    link_path "$dotfiles/vscode/app/settings.json" "$editor_root/settings.json"
    link_path "$dotfiles/vscode/app/keybindings.json" "$editor_root/keybindings.json"
    link_path "$dotfiles/vscode/app/snippets" "$editor_root/snippets"
  done

  copy_path "$workspace_home/.trae/sandbox.json" "$HOME/.trae/sandbox.json" 0600
  copy_path "$workspace_home/.trae/traecli.toml" "$HOME/.trae/traecli.toml" 0600
  copy_path "$workspace_home/.trae-cn/sandbox.json" "$HOME/.trae-cn/sandbox.json" 0600
  copy_path "$workspace_home/.trae-cn/traecli.toml" "$HOME/.trae-cn/traecli.toml" 0600
}

load_launch_agent() {
  local label="$1"
  local plist="$2"
  local target="$HOME/Library/LaunchAgents/${label}.plist"
  local domain
  domain="gui/$(id -u)"

  link_path "$plist" "$target"
  launchctl bootout "$domain/$label" >/dev/null 2>&1 || true
  launchctl bootstrap "$domain" "$target"
  launchctl kickstart -k "$domain/$label"
}

main() {
  if ((BASH_VERSINFO[0] < 3)); then
    printf 'error: Bash 3.2 or newer is required\n' >&2
    return 2
  fi

  local with_atuin_server=false
  while (($# > 0)); do
    case "$1" in
      --with-atuin-server)
        # shellcheck disable=SC2034
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

  local script_dir repo_root dotfiles workspace_home
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
  repo_root="$(cd "$script_dir/../.." && pwd -P)"
  dotfiles="$repo_root/dotfiles"
  workspace_home="$repo_root/platform/container/workspace/rootfs/home/x"
  TEMP_DIR="$(mktemp -d)"
  trap cleanup EXIT

  install_homebrew "$script_dir" "$TEMP_DIR"
  install_binman "$script_dir" "$TEMP_DIR"
  install_dotfiles "$dotfiles" "$script_dir" "$workspace_home"
  swift "$script_dir/scripts/set-default-apps.swift"
  load_launch_agent sh.atuin.daemon "$script_dir/launch-agents/atuin-daemon.plist"
  if [[ "$with_atuin_server" == true ]]; then
    load_launch_agent sh.atuin.server "$script_dir/launch-agents/atuin-server.plist"
  fi
}

main "$@"
