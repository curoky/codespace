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

pkgs=(
  bzip2
  clang-format_18
  clang-format_19
  clang-format_20
  clang-format_21
  connect
  dool
  ethtool
  fzf
  gdu
  go-task
  # inetutils
  iproute2
  iputils
  jq
  krb5
  libcap
  lsb-release
  makeself
  miniserve
  ncdu_1
  netcat
  netron
  nettools
  openssl
  patchelf
  procps
  rsync
  snappy
  strace
  xxd
  xz
  zlib
  zlib-ng
  zstd
  tmux
  tmux-extra
  vim
  vim-extra
  ripgrep
  cmake
  git
  lefthook
  uv
  yazi

  ####  too basic tool
  cacert
  curl
  diffutils
  fd
  file
  findutils
  gawk
  getopt
  gettext
  gnugrep
  gnumake
  gnupatch
  gnused
  gnutar
  gzip
  less
  lsof
  m4
  pkg-config
  tree
  unzip
  # util-linux
  wget
  zip
  autoconf
  automake
  libtool

  #### only use in docker
  atuin
  bat
  bazelisk
  bison
  buildifier
  exiftool
  eza
  flex
  git-absorb
  git-extras
  git-filter-repo
  git-lfs
  glibcLocales
  gnupg-minimal
  ninja
  openssh_gssapi
  procs
  protobuf_24
  protobuf_25
  protobuf_28
  protobuf_3_8_0
  protobuf_3_9_2
  ruff
  shfmt
  starship
  tzdata
  zsh-bundle
  cronie
  p7zip

  ##### unneeded
  # aria2
  # binutils
  # coreutils
  # croc
  # dive
  # gh
  # gost
  # iptables
  # lld_18
  # nixfmt-rfc-style
  # nixpkgs-fmt
  # numactl
  # scc
  # silver-searcher

  ##### experimental
  # bash
  gdb
  # man
  perl
)

curl https://raw.githubusercontent.com/curoky/static-binaries/refs/heads/master/tools/multi-install.sh >/tmp/install.sh
for pkg in "${pkgs[@]}"; do
  bash /tmp/install.sh -n $pkg -i /opt/tools -l -p /opt/tools/ &
done
bash /tmp/install.sh -n python311 -i /opt/tools &
wait
rm -rf /opt/tools/downloads

ln -s -r /opt/tools/bin/bazelisk /opt/tools/bin/bazel
ln -s -r /opt/tools/bin/clang-format-21 /opt/tools/bin/clang-format
rm -rf /opt/tools/store/nettools/bin/hostname
