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

for f in "$CONFIG_HOME"/zsh/lib/*.sh; do
  source "$f"
done

#=-> homebrew
if [[ -f $HOMEBREW_PREFIX/bin/brew ]]; then
  eval "$($HOMEBREW_PREFIX/bin/brew shellenv)"
fi

#=-> nix
source_if_exists ~/.nix-profile/etc/profile.d/nix.sh

#=-> start oh-my-zsh
source /workspace/zinit/zinit.zsh

zinit ice blockf
zinit light zsh-users/zsh-completions

# zinit light zsh-users/zsh-syntax-highlighting
zinit light zdharma-continuum/fast-syntax-highlighting


zinit snippet OMZ::plugins/git/git.plugin.zsh
zinit snippet OMZ::plugins/extract/extract.plugin.zsh

zinit ice atclone"starship init zsh > init.zsh; starship completions zsh > _starship" \
          atpull"%atclone" src"init.zsh"
zinit light starship/starship

zinit ice atclone"atuin init zsh --disable-up-arrow > init.zsh; atuin gen-completions --shell zsh > _atuin" \
          atpull"%atclone" src"init.zsh"
zinit light @atuinsh/atuin

autoload compinit
compinit
#zinit ice from"bin" src="starship"
#zinit light starship

# zinit ice --quiet as'null' from"gh-r" lbin'!' lucid nocompile completions
# zinit atclone'./atuin init zsh --disable-up-arrow >> zhook.zsh && ./atuin gen-completions --shell zsh > _atuin' atpull'%atclone' \
#      src="zhook.zsh" wait'0b' lucid  \
#      atload'ZSH_AUTOSUGGEST_STRATEGY=(atuin);_zsh_autosuggest_strategy_atuin() { typeset -g suggestion; suggestion="$(atuin search --limit 1 --search-mode prefix --cmd-only "$1")"; }' for \
#    @atuinsh/atuin

# #=-> conda
# if [[ -f ~/opt/conda/bin/conda ]]; then
#   eval "$(~/opt/conda/bin/conda shell.zsh hook 2>/dev/null)"
# fi
# if [[ -f /opt/homebrew/Caskroom/miniconda/base/bin/conda ]]; then
#   eval "$(/opt/homebrew/Caskroom/miniconda/base/bin/conda shell.zsh hook 2>/dev/null)"
# fi

# # TODO: remove -u
# # why: why add -u to compinit?
# # ref: https://stackoverflow.com/questions/13762280/zsh-compinit-insecure-directories
# # for error:
# #   zsh compinit: insecure directories, run compaudit for list.
# #   Ignore insecure directories and continue [y] or abort compinit [n]?
# # autoload -zU compinit && compinit -u
# autoload -U compinit && compinit -u

# # compdef _bb bb bbup bb4 bb4up bbcl bbclup

# # TODO: remove follow
# # zstyle ':completion:*' menu select
# # unset zle_bracketed_paste

# #-> (post) starship
# eval "$(starship init zsh)"

# #-> (post) mcfly
# # eval "$(mcfly init zsh)"

# #-> (post) atuin
# eval "$(atuin init zsh --disable-up-arrow)"
