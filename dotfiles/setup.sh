#!/usr/bin/env bash
# Copyright (c) 2018-2025 curoky(cccuroky@gmail.com).
#
# This file is part of devspace.
# See https://github.com/curoky/devspace for further info.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
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
  mkdir -p $(dirname "$dst")
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
  if [[ -e $dst ]] || [[ -L $dst ]]; then
    echo "Path $dst already exists, move it to backup"
    rm -rf "$dst"
    # mv $dst ${dst}.bk
  fi
  mkdir -p $(dirname "$dst")
  ln -s "$src" "$dst"
  echo "Linked $src to $dst"
}

SCENE=${1}
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

  # link_path $CONF_PATH/gdb/gdbinit $HOME/.gdbinit
  link_path $CONF_PATH/vim/vimrc $HOME/.vimrc
  # link_path $CONF_PATH/tabby-ml/config.toml $HOME/.tabby-client/agent/config.toml

  copy_path $CONF_PATH/zsh/prune.zshrc $HOME/.zshrc
  copy_path $CONF_PATH/git/.gitconfig $HOME/.gitconfig
  copy_path $CONF_PATH/ssh/user.ssh_config $HOME/.ssh/config
}

common

if [[ $SCENE == "host-macos" ]]; then
  link_path $CONF_PATH/rime/squirrel $HOME/Library/Rime
  link_path $CONF_PATH/snipaste/config.ini $HOME/.snipaste/config.ini
  link_path $CONF_PATH/vscode/app/snippets "$HOME/Library/Application Support/Code/User/snippets"
  link_path $CONF_PATH/vscode/app/keybindings.json "$HOME/Library/Application Support/Code/User/keybindings.json"
  link_path $CONF_PATH/vscode/app/settings.json "$HOME/Library/Application Support/Code/User/settings.json"

elif [[ $SCENE == "host-linux" ]]; then
  link_path $CONF_PATH/vscode/remote-server-settings.json $HOME/.vscode-server/data/Machine/settings.json
  rm -rf ~/.gitconfig
  rm -rf ~/.ssh/config
  rm -rf ~/.gdbinit
  rm -rf ~/.tabby-client

elif [[ $SCENE == "docker" ]]; then
  link_path $CONF_PATH/vscode/remote-server-settings.json $HOME/.vscode-server/data/Machine/settings.json

fi
