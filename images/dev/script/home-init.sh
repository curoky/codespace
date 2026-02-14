#!/usr/bin/env bash

set -xeuo pipefail

# clean cache
# rm -rf /home/x/.cache/starship.plugin.zsh \
#   /home/x/.cache/conda.plugin.zsh \
#   /home/x/.cache/atuin.plugin.zsh

# sudo -E /opt/devspace/images/dev/script/setup-proxy.sh
function link() {
  local workspace_dir="/workspace/.cache/$1"
  local home_dir="/home/x/$1"
  mkdir -p "$workspace_dir"
  rm -rf "$home_dir"
  ln -sf "$workspace_dir" "$home_dir"
}

link .vscode-server
link .trae
link .trae-cn
link .trae-server
link .trae-cn-server

bash /opt/devspace/dotfiles/setup.sh docker /opt/devspace/dotfiles
bash /opt/agent-playbook/install.sh
cp /opt/devspace/images/dev/dev-environment.md /home/x/.trae/user_rules/
cp /opt/devspace/images/dev/dev-environment.md /home/x/.trae-cn/user_rules/
