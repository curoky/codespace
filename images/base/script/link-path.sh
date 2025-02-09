#!/usr/bin/env bash

set -xeuo pipefail

# reset dotfiles for x
if [[ -d /workspace/devspace ]]; then
  rm -rf /home/x/devspace
  ln -s /workspace/devspace /home/x/devspace
fi

# setup cache dir
mkdir -p /cache
chown x:x /cache
rm -rf /home/x/.cache
ln -s /cache /home/x/.cache

# setup vscode-server cache
mkdir -p /cache/vscode-server
chown x:x /cache/vscode-server
rm -rf /home/x/.vscode-server
ln -s /cache/vscode-server /home/x/.vscode-server

chown x:x /workspace
