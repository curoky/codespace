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
  tmux-plugs
  vim
  vim-plugs
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
  zsh
  zsh-plugs
  cronie
  p7zip
  parallel

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
  scc
  cloc
  # silver-searcher

  ##### experimental
  # bash
  gdb
  # man
  perl
)

mkdir -p /opt/sbt/bin
curl https://raw.githubusercontent.com/curoky/static-binaries/refs/heads/master/tools/sbt >/opt/sbt/bin/sbt
chmod +x /opt/sbt/bin/sbt
for pkg in "${pkgs[@]}"; do
  /opt/sbt/bin/sbt install $pkg &
done
/opt/sbt/bin/sbt install python311 --nolink &
wait

ln -s -r /opt/sbt/bin/bazelisk /opt/sbt/bin/bazel
ln -s -r /opt/sbt/bin/clang-format-21 /opt/sbt/bin/clang-format
rm -rf /opt/sbt/store/nettools/bin/hostname

# option
rm -rf /opt/sbt/store/cmake/share/cmake*/Help
rm -rf /opt/sbt/store/cmake/share/doc
rm -rf /opt/sbt/store/vim/share/vim/vim*/doc
rm -rf /opt/sbt/store/protobuf*/lib
