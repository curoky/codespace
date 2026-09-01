#!/usr/bin/env bash

set -euo pipefail

# 把构建期预装的扩展播种到各 IDE 远端 server（server 目录已软链到持久化的 /cache）。
bash /opt/devspace/images/dev/script/seed-vscode-extensions.sh \
  /home/x/.vscode-server /home/x/.trae-server /home/x/.trae-cn-server

bash /opt/devspace/dotfiles/setup.sh docker /opt/devspace/dotfiles
bash /opt/agent-playbook/install.sh
cp /opt/devspace/images/dev/dev-environment.md /home/x/.trae/user_rules/
cp /opt/devspace/images/dev/dev-environment.md /home/x/.trae-cn/user_rules/
