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

# just for macos
HOMEBREW_PREFIX=/opt/homebrew

if [[ -d /workspace ]]; then
  export WORKSPACE=/workspace
else
  export WORKSPACE=~/workspace
fi

export MY_HOST_NAME=$(hostname)

#=-> basic config
# export EDITOR=vim
# command -v vim >/dev/null && export EDITOR=vim

#=-> XDG
export XDG_CACHE_HOME=$HOME/.cache
export XDG_CONFIG_HOME=$HOME/.config
# just for vscode https://github.com/microsoft/vscode/blob/d2850a427c3f615c7ca94326c801d0fbdb303bad/src/vs/base/parts/ipc/node/ipc.net.ts#L518
export XDG_RUNTIME_DIR=$XDG_CACHE_HOME/runtime
export XDG_DATA_DIR=$XDG_CACHE_HOME/data
mkdir_if_not_exists $XDG_RUNTIME_DIR
mkdir_if_not_exists $XDG_DATA_DIR

#=-> tmp file path
export TMPDIR=$XDG_CACHE_HOME/tmp
mkdir_if_not_exists $TMPDIR

# kernel config
if [[ $(uname) == "Linux" ]]; then
  # https://superuser.com/questions/687094/does-ulimit-su-limit-the-number-of-user-processes-created-in-interactive-logi
  # https://github.com/tmux/tmux/issues/1356
  ulimit -Sn 1024768
fi
