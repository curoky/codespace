#!/usr/bin/env bash
set -xeuo pipefail

function copy_path() {
  src="$1"
  dst="$2"
  force=${3:-0}
  if [[ ! -e $src ]]; then
    echo "Path $src does not exist"
    if [[ $force -eq 0 ]]; then
      return
    fi
  fi
  if [[ -e $dst ]]; then
    echo "Path $dst already exists, move it to backup"
    rm -rf "$dst"
    # mv $dst ${dst}.bk
  fi
  mkdir -p "$(dirname "$dst")"
  cp -r "$src" "$dst"
  chmod 600 "$dst"
  echo "Copied $src to $dst"
}

function link_path() {
  src="$1"
  dst="$2"
  ignore_source_not_exist=${3:-0}
  if [[ ! -e $src ]]; then
    echo "Path $src does not exist"
    if [[ $ignore_source_not_exist -eq 0 ]]; then
      return
    fi
  fi
  mkdir -p "$(dirname "$dst")"
  # A real file/dir occupying dst only happens on first provisioning (no
  # concurrent reader yet), so removing it here is safe. In steady state dst is
  # already our symlink and this branch is skipped.
  if [[ -e $dst && ! -L $dst ]]; then
    echo "Path $dst is a real file/dir, removing before linking"
    rm -rf "$dst"
  fi
  # A symlink pointing at a directory would make the mv below descend into it
  # (creating dst/<tmp>) instead of replacing the link. Those targets are the
  # macOS-only snippets dirs, run once during host setup with no concurrent
  # reader, so dropping the stale link first is safe here.
  if [[ -L $dst && -d $dst ]]; then
    rm -f "$dst"
  fi
  # Replace the (file) symlink atomically: create it under a sibling temp name,
  # then rename(2) it over dst. rename is atomic, so a re-link (e.g. home-init
  # re-running setup.sh) never leaves a window where dst is missing and a
  # consumer like atuin falls back to its default (public) config. A
  # PID-suffixed sibling keeps the temp on the same filesystem so the rename
  # stays atomic, and this works on both GNU and BSD/macOS.
  tmp="$dst.link-tmp.$$"
  ln -sf "$src" "$tmp"
  mv -f "$tmp" "$dst"
  echo "Linked $src to $dst"
}

# CONF_PATH: dotfiles dir (scene-specific / macOS-desktop configs).
# ROOTFS_HOME: baked container home (images/dev/rootfs/home/x), the source of
# truth for cross-scene home configs since they are COPYed into the dev image.
# On non-container scenes we link the same files from here so there is a single
# source for every shared config.
CONF_PATH=${2:-$HOME/devspace/dotfiles} # TODO: remove default, verify all callers
REPO_ROOT=$(cd "$(dirname "$CONF_PATH")" && pwd)
ROOTFS_HOME="$REPO_ROOT/images/dev/rootfs/home/x"

# Scene selection: explicit first arg wins; otherwise infer from the OS.
# - docker:     dev container runtime (home-init). Static home configs are
#               already baked via `COPY rootfs/ /`, so only the dirs that
#               home-init relinks onto /workspace are (re)written here.
# - host-linux: bare Linux host without the baked rootfs; provision the full set.
# - darwin:     macOS host (default when run with no args by setup-homebrew.sh).
SCENE=${1:-}
if [[ -z $SCENE ]]; then
  if [[ $(uname -s) == "Darwin" ]]; then
    SCENE="darwin"
  else
    SCENE="host-linux"
  fi
fi

# Cross-scene home configs, sourced from the baked container home. Skipped in
# the docker scene where rootfs already put them at these paths.
function shared_home() {
  link_path $ROOTFS_HOME/.config/atuin/config.toml $HOME/.config/atuin/config.toml
  link_path $ROOTFS_HOME/.config/bat/config $HOME/.config/bat/config
  link_path $ROOTFS_HOME/.config/conda/condarc $HOME/.config/conda/condarc
  link_path $ROOTFS_HOME/.config/nixpkgs/config.nix $HOME/.config/nixpkgs/config.nix
  link_path $ROOTFS_HOME/.config/procps/toprc $HOME/.config/procps/toprc
  link_path $ROOTFS_HOME/.config/starship.toml $HOME/.config/starship.toml
  link_path $ROOTFS_HOME/.config/tmux/tmux.conf $HOME/.config/tmux/tmux.conf
  link_path $ROOTFS_HOME/.config/zellij/config.kdl $HOME/.config/zellij/config.kdl
  link_path $ROOTFS_HOME/.vimrc $HOME/.vimrc
}

# Configs that land in dirs home-init relinks onto /workspace at boot; baking
# them into rootfs would be wiped by that relink, so they are (re)applied at
# runtime from dotfiles instead.
function trae_runtime() {
  copy_path $CONF_PATH/trae/sandbox.json $HOME/.trae/sandbox.json
  copy_path $CONF_PATH/trae/traecli.toml $HOME/.trae/traecli.toml
  copy_path $CONF_PATH/trae/sandbox.json $HOME/.trae-cn/sandbox.json
  copy_path $CONF_PATH/trae/traecli.toml $HOME/.trae-cn/traecli.toml
}

function vscode_remote_runtime() {
  link_path $CONF_PATH/vscode/remote-server-settings.json $HOME/.vscode-server/data/Machine/settings.json
  link_path $CONF_PATH/vscode/remote-server-settings.json $HOME/.trae-server/data/Machine/settings.json
  link_path $CONF_PATH/vscode/remote-server-settings.json $HOME/.trae-cn-server/data/Machine/settings.json
}

case $SCENE in
docker)
  trae_runtime
  vscode_remote_runtime
  ;;

host-linux)
  shared_home
  trae_runtime
  vscode_remote_runtime
  link_path $ROOTFS_HOME/.bazelrc $HOME/.bazelrc
  copy_path $CONF_PATH/zsh/prune.zshrc $HOME/.zshrc
  copy_path $CONF_PATH/git/.gitconfig $HOME/.gitconfig
  ;;

darwin)
  shared_home
  trae_runtime

  # link_path $CONF_PATH/rime/squirrel $HOME/Library/Rime
  link_path $CONF_PATH/snipaste/config.ini $HOME/.snipaste/config.ini
  link_path $CONF_PATH/mpv/mpv.conf $HOME/.config/mpv/mpv.conf
  link_path $CONF_PATH/warp/settings.toml $HOME/.warp/settings.toml

  link_path $CONF_PATH/vscode/app/snippets "$HOME/Library/Application Support/Code/User/snippets"
  link_path $CONF_PATH/vscode/app/keybindings.json "$HOME/Library/Application Support/Code/User/keybindings.json"
  link_path $CONF_PATH/vscode/app/settings.json "$HOME/Library/Application Support/Code/User/settings.json"

  link_path $CONF_PATH/vscode/app/settings.json "$HOME/Library/Application Support/Trae/User/settings.json"
  link_path $CONF_PATH/vscode/app/keybindings.json "$HOME/Library/Application Support/Trae/User/keybindings.json"
  link_path $CONF_PATH/vscode/app/snippets "$HOME/Library/Application Support/Trae/User/snippets"

  link_path $CONF_PATH/vscode/app/settings.json "$HOME/Library/Application Support/Trae CN/User/settings.json"
  link_path $CONF_PATH/vscode/app/keybindings.json "$HOME/Library/Application Support/Trae CN/User/keybindings.json"
  link_path $CONF_PATH/vscode/app/snippets "$HOME/Library/Application Support/Trae CN/User/snippets"

  link_path $CONF_PATH/launchctl/sh.atuin.daemon.plist "$HOME/Library/LaunchAgents/sh.atuin.daemon.plist"
  # copy_path $CONF_PATH/launchctl/sh.atuin.server.plist "$HOME/Library/LaunchAgents/sh.atuin.server.plist"
  ;;

*)
  echo "Unknown scene: $SCENE (expected docker|host-linux|darwin)"
  exit 1
  ;;
esac
