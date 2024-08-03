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

mkdir -p /workspace/.vscode-server/data/Machine
ln -sf /home/x/.vscode-server/data/Machine/settings.json /workspace/.vscode-server/data/Machine/settings.json

/opt/devspace/tools/profile-installer.sh --ssl-pass-src pass:$(cat /var/run/s6/container_environment/PROFILE_PASS)
/home/x/.config/atuin/login-and-sync.sh &

# export PATH=$PATH:/opt/rust/cargo/bin:/opt/sbt/bin
# /opt/devspace/images/base/stage/uv/conda/install.sh py3 &

# clean cache
rm -rf /home/x/.cache/starship.plugin.zsh \
  /home/x/.cache/conda.plugin.zsh \
  /home/x/.cache/atuin.plugin.zsh

# ollama pull llama3:8b &
# ollama pull mistral &

wait
