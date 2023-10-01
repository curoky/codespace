# Copyright (c) 2018-2024 curoky(cccuroky@gmail.com).
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

export CONFIG_HOME=~/devspace/dotfiles
export TOOLS_ROOT=/opt/tools
if [[ ! -d $TOOLS_ROOT ]]; then
  export TOOLS_ROOT=$HOME/app/tools
fi

for f in "$CONFIG_HOME"/zsh/lib/*.sh; do
  source "$f"
done

#=-> homebrew
if [[ -f $HOMEBREW_PREFIX/bin/brew ]]; then
  eval "$($HOMEBREW_PREFIX/bin/brew shellenv)"
fi

export ZSH=$TOOLS_ROOT/store/zsh-bundle/share/oh-my-zsh
# https://github.com/ohmyzsh/ohmyzsh/blob/7ed475cb589c9e82211f71b3a5d7083b69cea93c/oh-my-zsh.sh#L132
autoload -Uz compinit # zrecompile compaudit
compinit -u -d $XDG_CACHE_HOME/.zcompdump

source ${ZSH}/lib/history.zsh
source ${ZSH}/lib/completion.zsh
source ${ZSH}/lib/key-bindings.zsh
source ${ZSH}/lib/directories.zsh
source ${ZSH}/lib/git.zsh
source ${ZSH}/plugins/extract/extract.plugin.zsh
source ${ZSH}/plugins/git/git.plugin.zsh
source ${ZSH}/custom/plugins/zsh-autosuggestions/zsh-autosuggestions.zsh
source ${ZSH}/custom/plugins/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh

if [[ ! -f $XDG_CACHE_HOME/starship.plugin.zsh ]] && command -v starship >/dev/null 2>&1; then
  starship init zsh > $XDG_CACHE_HOME/starship.plugin.zsh
fi
source $XDG_CACHE_HOME/starship.plugin.zsh

if [[ ! -f $XDG_CACHE_HOME/atuin.plugin.zsh ]] && command -v atuin >/dev/null 2>&1; then
  atuin init zsh --disable-up-arrow > $XDG_CACHE_HOME/atuin.plugin.zsh
fi
source $XDG_CACHE_HOME/atuin.plugin.zsh

if [[ ! -f $XDG_CACHE_HOME/conda.plugin.zsh ]] && command -v conda >/dev/null 2>&1; then
  conda shell.zsh hook 2>/dev/null > $XDG_CACHE_HOME/conda.plugin.zsh
fi
source $XDG_CACHE_HOME/conda.plugin.zsh
