#!/usr/bin/env bash
set -euo pipefail

macos_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
macos_home="$macos_dir/rootfs/Users/x"
workspace_home="$(cd "$macos_dir/../container/workspace/rootfs/home/x" && pwd -P)"

link_home_path() {
  local source_root="$1"
  local source_path="$2"
  local destination_path="${3:-$source_path}"
  local mode="${4:-0600}"
  local source="$source_root/$source_path"
  local destination="$HOME/$destination_path"

  [[ -e "$source" ]] || {
    printf 'error: source does not exist: %s\n' "$source" >&2
    return 1
  }
  [[ ! -f "$source" ]] || chmod "$mode" "$source"
  if [[ -L "$destination" && "$(readlink "$destination")" == "$source" ]]; then
    return
  fi

  mkdir -p "$(dirname "$destination")"
  rm -rf "$destination"
  ln -s "$source" "$destination"
  printf 'linked %s -> %s\n' "$destination" "$source"
}

copy_home_path() {
  local source_root="$1"
  local relative_path="$2"
  local source="$source_root/$relative_path"
  local destination="$HOME/$relative_path"

  [[ -f "$source" ]] || {
    printf 'error: source does not exist: %s\n' "$source" >&2
    return 1
  }
  mkdir -p "$(dirname "$destination")"
  rm -rf "$destination"
  install -m 0600 "$source" "$destination"
  printf 'installed %s\n' "$destination"
}

install -d -m 0700 "$HOME/.ssh" "$HOME/.ssh/codespace" \
  "$HOME/.ssh/codespace/known_hosts" "$HOME/.ssh/codespace/workspaces"

link_home_path "$workspace_home" ".gitconfig"
link_home_path "$workspace_home" ".gitignore_global"
link_home_path "$macos_home" ".config/git/user.gitconfig"
link_home_path "$macos_home" ".ssh/config"
link_home_path "$macos_home" ".ssh/codespace/config"
link_home_path "$workspace_home" ".ssh/workspace_login_key_ed25519" \
  ".ssh/codespace/workspace_login_key_ed25519"
link_home_path "$macos_home" ".ssh/codespace/known_hosts/codespace"

link_home_path "$macos_home" ".zshrc"
link_home_path "$workspace_home" ".config/zsh/aliases.zsh"
link_home_path "$workspace_home" ".config/zsh/functions.zsh"
link_home_path "$workspace_home" ".config/zsh/git.zsh"
link_home_path "$workspace_home" ".config/atuin/config.toml"
link_home_path "$workspace_home" ".config/bat/config"
link_home_path "$workspace_home" ".config/nixpkgs/config.nix"
link_home_path "$workspace_home" ".config/starship.toml"
link_home_path "$workspace_home" ".config/tmux/tmux.conf"
link_home_path "$workspace_home" ".local/bin/eza-wrapper" ".local/bin/eza-wrapper" 0755
link_home_path "$workspace_home" ".vimrc"

link_home_path "$macos_home" ".codex/AGENTS.md"
rm -rf "$HOME/.codex/skills/manage-software" "$HOME/.trae-cn/skills/manage-software"
link_home_path "$macos_home" ".config/mpv/mpv.conf"
link_home_path "$macos_home" ".snipaste/config.ini"
link_home_path "$macos_home" ".warp/settings.toml"

for editor in Code Trae "Trae CN"; do
  link_home_path "$macos_home" "Library/Application Support/$editor/User/settings.json"
  link_home_path "$macos_home" "Library/Application Support/$editor/User/keybindings.json"
  link_home_path "$macos_home" "Library/Application Support/$editor/User/snippets"
done

copy_home_path "$workspace_home" ".trae/sandbox.json"
copy_home_path "$workspace_home" ".trae/traecli.toml"
copy_home_path "$workspace_home" ".trae-cn/sandbox.json"
copy_home_path "$workspace_home" ".trae-cn/traecli.toml"
