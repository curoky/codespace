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

OS_NAME=$(uname -o)

CONF_PATH=${2:-$HOME/devspace/dotfiles} # TODO: remove

function common() {
  link_path $CONF_PATH/atuin/config.toml $HOME/.config/atuin/config.toml
  link_path $CONF_PATH/bat/config $HOME/.config/bat/config
  link_path $CONF_PATH/conda/condarc $HOME/.config/conda/condarc
  # link_path $CONF_PATH/croc/classic_enabled $HOME/.config/croc/classic_enabled
  # link_path $CONF_PATH/go/env $HOME/.config/go/env
  link_path $CONF_PATH/nixpkgs/config.nix $HOME/.config/nixpkgs/config.nix
  link_path $CONF_PATH/procps/toprc $HOME/.config/procps/toprc
  link_path $CONF_PATH/starship/starship.toml $HOME/.config/starship.toml
  link_path $CONF_PATH/tmux/tmux.conf $HOME/.config/tmux/tmux.conf
  link_path $CONF_PATH/zellij/config.kdl $HOME/.config/zellij/config.kdl

  # link_path $CONF_PATH/gdb/gdbinit $HOME/.gdbinit
  link_path $CONF_PATH/vim/vimrc $HOME/.vimrc
  # link_path $CONF_PATH/tabby-ml/config.toml $HOME/.tabby-client/agent/config.toml

  copy_path $CONF_PATH/trae/sandbox.json $HOME/.trae/sandbox.json
  copy_path $CONF_PATH/trae/traecli.toml $HOME/.trae/traecli.toml
  copy_path $CONF_PATH/trae/sandbox.json $HOME/.trae-cn/sandbox.json
  copy_path $CONF_PATH/trae/traecli.toml $HOME/.trae-cn/traecli.toml

  # copy_path $CONF_PATH/zsh/prune.zshrc $HOME/.zshrc
  # copy_path $CONF_PATH/git/.gitconfig $HOME/.gitconfig
  # copy_path $CONF_PATH/ssh/user.ssh_config $HOME/.ssh/config
  # copy_path $CONF_PATH/ssh/authorized_keys $HOME/.ssh/authorized_keys
}

common

if [[ $OS_NAME == "Darwin" ]]; then
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

else
  link_path $CONF_PATH/vscode/remote-server-settings.json $HOME/.vscode-server/data/Machine/settings.json
  link_path $CONF_PATH/vscode/remote-server-settings.json $HOME/.trae-server/data/Machine/settings.json
  link_path $CONF_PATH/vscode/remote-server-settings.json $HOME/.trae-cn-server/data/Machine/settings.json

  link_path $CONF_PATH/bazel/bazelrc $HOME/.bazelrc

  copy_path $CONF_PATH/zsh/prune.zshrc $HOME/.zshrc
  copy_path $CONF_PATH/git/.gitconfig $HOME/.gitconfig
fi
