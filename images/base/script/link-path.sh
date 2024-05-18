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
