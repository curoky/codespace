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

# task --list-all | sed -e 's/://g' -e 's/*//g'
pkgs=(
  atuin
  bat
  bzip2
  connect
  coreutils
  eza
  fd
  findutils
  fzf
  gawk
  gdu
  getopt
  gettext
  git-absorb
  git-extras
  git-lfs
  gnugrep
  gnupatch
  gnused
  gnutar
  go-task
  # inetutils
  lsof
  m4
  makeself
  ncdu_1
  netcat
  openssl
  # rime-plugins
  rsync
  shfmt
  starship
  unzip
  vim-plugins
  xz
  zip
  zsh-plugins
  zstd
  buildifier
  ripgrep
  # tmux
  # tmux-plugins
  lefthook
  bazelisk
  uv
  ruff
  yazi
  # git
  git-filter-repo
  biome

  # lxgw-wenkai
  # fira-code
  # nerd-fonts.fira-code
  # nerd-fonts.ubuntu-mono

  ##### unneeded
  # vim
  # zsh
  # aria2
  # gost

  # ruff need link jemalloc
)

sudo mkdir -p /opt/sb
sudo chown x:staff /opt/sb

# Bootstrap the sb client into the prefix, then use it to install everything.
mkdir -p /opt/sb/bin
curl -fsSL https://raw.githubusercontent.com/curoky/standalone-binaries/refs/heads/master/client/install.sh |
  bash -s -- --prefix /opt/sb/bin

# sb install takes many packages at once and parallelizes internally
# (resolve + download), so no shell-level background/wait loop is needed.
/opt/sb/bin/sb install --prefix /opt/sb "${pkgs[@]}"

ln -sf /opt/sb/bin/bazelisk /opt/sb/bin/bazel
