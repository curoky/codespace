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

/opt/devspace/images/base/script/start-sshd.sh $SSHD_PORT
sudo -u x bash /opt/devspace/tools/profile-installer.sh --ssl-pass-src pass:$PROFILE_PASS
sudo -u x bash /home/x/.config/atuin/login-and-sync.sh &

sudo -u x bash /opt/devspace/images/base/script/backgroup-task.sh &

# clean cache
rm -rf /home/x/.cache/starship.plugin.zsh \
  /home/x/.cache/conda.plugin.zsh \
  /home/x/.cache/atuin.plugin.zsh

while true; do sleep 86400; done
