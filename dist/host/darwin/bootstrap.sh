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

if [[ ! -f /opt/homebrew/bin/brew ]]; then
  export NONINTERACTIVE=1
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

eval "$(/opt/homebrew/bin/brew shellenv)"

rm -rf ~/devspace
ln -s ~/workspace/devspace ~/devspace
~/devspace/dotfiles/setup.sh host-macos $HOME/devspace/dotfiles

brew bundle --force --file ~/devspace/dist/host/darwin/conf/brew/Brewfile.personal --cleanup --verbose
# brew link krb5 --force
brew cleanup --prune=all

curl -sSL https://github.com/curoky/devspace/raw/master/deps/host-tools/tools/online-installer.sh | bash
curl -sSL https://github.com/curoky/devspace/raw/master/deps/host-tools/conda/online-installer.sh | bash
