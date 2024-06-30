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
  inetutils
  lsof
  m4
  makeself
  ncdu_1
  netcat
  openssl
  # rime-plugs
  rsync
  shfmt
  starship
  unzip
  vim-plugs
  xz
  zip
  zsh-plugs
  zstd
  buildifier
  ripgrep
  # tmux
  # tmux-plugs
  lefthook
  bazelisk
  uv
  ruff
  yazi
  # git

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

sudo mkdir -p /opt/sbt
sudo chown x:staff /opt/sbt

mkdir -p /opt/sbt/bin
curl https://raw.githubusercontent.com/curoky/static-binaries/refs/heads/master/tools/sbt >/opt/sbt/bin/sbt
chmod +x /opt/sbt/bin/sbt
/opt/sbt/bin/sbt install coreutils
for pkg in "${pkgs[@]}"; do
  /opt/sbt/bin/sbt install $pkg & # --arch darwin-arm64 --prefix tmp/sbt
done
wait

ln -sf /opt/sbt/bin/bazelisk /opt/sbt/bin/bazel
