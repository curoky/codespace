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
  if [[ -e $dst ]] || [[ -L $dst ]]; then
    echo "Path $dst already exists, move it to backup"
    rm -rf "$dst"
    # mv $dst ${dst}.bk
  fi
  mkdir -p "$(dirname "$dst")"
  ln -s "$src" "$dst"
  echo "Linked $src to $dst"
}

OS_NAME=$(uname -o)

SCENE=${1:-docker}
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

  copy_path $CONF_PATH/zsh/prune.zshrc $HOME/.zshrc
  copy_path $CONF_PATH/git/.gitconfig $HOME/.gitconfig
  copy_path $CONF_PATH/ssh/user.ssh_config $HOME/.ssh/config
  copy_path $CONF_PATH/ssh/authorized_keys $HOME/.ssh/authorized_keys
}

common

if [[ $OS_NAME == "Darwin" ]]; then
  # link_path $CONF_PATH/rime/squirrel $HOME/Library/Rime
  link_path $CONF_PATH/snipaste/config.ini $HOME/.snipaste/config.ini
  link_path $CONF_PATH/trae/sandbox.json $HOME/.trae/sandbox.json
  # link_path $CONF_PATH/trae/traecli.yaml $HOME/.trae/traecli.yaml
  link_path $CONF_PATH/trae/traecli.toml $HOME/.trae/traecli.toml
  link_path $CONF_PATH/vscode/app/snippets "$HOME/Library/Application Support/Code/User/snippets"
  link_path $CONF_PATH/vscode/app/keybindings.json "$HOME/Library/Application Support/Code/User/keybindings.json"
  link_path $CONF_PATH/vscode/app/settings.json "$HOME/Library/Application Support/Code/User/settings.json"

  link_path $CONF_PATH/vscode/app/settings.json "$HOME/Library/Application Support/Trae/User/settings.json"
  link_path $CONF_PATH/vscode/app/keybindings.json "$HOME/Library/Application Support/Trae/User/keybindings.json"
  link_path $CONF_PATH/vscode/app/snippets "$HOME/Library/Application Support/Trae/User/snippets"

elif [[ $SCENE == "host-linux" ]]; then
  link_path $CONF_PATH/vscode/remote-server-settings.json $HOME/.vscode-server/data/Machine/settings.json
  rm -rf ~/.gitconfig
  rm -rf ~/.ssh/config
  # rm -rf ~/.gdbinit
  # rm -rf ~/.tabby-client

elif [[ $SCENE == "docker" ]]; then
  link_path $CONF_PATH/vscode/remote-server-settings.json $HOME/.vscode-server/data/Machine/settings.json
  link_path $CONF_PATH/trae/traecli.yaml $HOME/.trae/traecli.yaml
  link_path $CONF_PATH/bazel/bazelrc $HOME/.bazelrc
fi
