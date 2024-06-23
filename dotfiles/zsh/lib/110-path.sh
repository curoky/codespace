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

ENV_PATHS=(
  # "$HOMEBREW_PREFIX/opt/ruby/bin"
  "/opt/sbt/bin"
  "/nix/var/nix/profiles/default/bin"
)
for p in "${ENV_PATHS[@]}"; do
  [[ -d $p ]] && export PATH=$p:$PATH
done

ENV_PATHS=(

  "$HOME/.local/bin"
  "$HOME/.nix-profile/bin"

  "/opt/conda/condabin"
  "/opt/pipx/bin"
  "/opt/rust/cargo/bin"

  # "$HOME/app/conda/condabin"
  # "$HOME/app/conda/pipx/bin"
  "$HOMEBREW_PREFIX/opt/ruby/bin"

  # "$HOME/.npm-global/bin"
  "$HOME/devspace/tools"

  # "/nix/var/nix/profiles/default/lib/ruby/gems/2.7.0/bin"
  # "$HOMEBREW_PREFIX/lib/ruby/gems/3.1.0/bin"
  # "$HOME/.cargo/bin" # already source in ~/.zshenv
)
for p in "${ENV_PATHS[@]}"; do
  [[ -d $p ]] && export PATH=$PATH:$p
done

ENV_FPATHS=(
  "$HOMEBREW_PREFIX/completions/zsh"

  "/opt/sbt/share/zsh/site-functions"
  "/opt/sbt/store/zsh-bundle/share/oh-my-zsh/custom/plugins/zsh-completions/src"
  "/opt/sbt/store/zsh-bundle/share/oh-my-zsh/custom/plugins/conda-zsh-completion"
)

for p in "${ENV_FPATHS[@]}"; do
  [[ -d $p ]] && fpath=($p $fpath)
done

ENV_PATHS=(
)

for p in "${ENV_PATHS[@]}"; do
  [[ -d $p ]] && export PYTHONPATH=$p:$PYTHONPATH
done
