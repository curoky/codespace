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

function link() {
  local src_dir=$1
  local dst_dir=$2
  find "$src_dir" \( -type f -o -type l \) | while read -r file; do
    rel_path="${file#$src_dir/}"
    dest_file="$dst_dir/$rel_path"
    mkdir -p "$(dirname "$dest_file")"
    if [[ -L $dest_file ]] || [[ -f $dest_file ]]; then
      rm "$dest_file"
    fi
    ln -s -r "$file" "$dest_file"
  done
}

pkgs=(
  bzip2
  clang-tools-22
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
  tmux-plugins
  vim
  vim-plugins
  ripgrep
  cmake
  git
  lefthook
  uv
  yazi
  sqlite
  gh
  nil

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
  gnupg
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
  zsh-plugins
  cronie
  p7zip
  parallel
  nixfmt

  ##### unneeded
  # aria2
  # binutils
  # coreutils
  # croc
  # dive
  # gost
  # iptables
  # lld_18
  # numactl
  # silver-searcher
  scc
  cloc

  ##### experimental
  # bash
  gdb
  # man
  perl
)

pkgs_nolink=(
  python311

  clang-tools-18
  clang-tools-19
  clang-tools-20
  clang-tools-21

  s6
  s6-rc
  s6-linux-init
  s6-linux-utils
  s6-portable-utils
  s6-networking
  s6-dns
  execline
)

# Bootstrap the sb client into the prefix, then use it to install everything.
mkdir -p /opt/sb/bin
curl -fsSL https://raw.githubusercontent.com/curoky/standalone-binaries/refs/heads/master/client/install.sh |
  bash -s -- --prefix /opt/sb/bin

# sb install takes many packages at once and parallelizes internally
# (resolve + download), so no shell-level background/wait loop is needed.
/opt/sb/bin/sb install --prefix /opt/sb "${pkgs[@]}"
/opt/sb/bin/sb install --prefix /opt/sb --link=false "${pkgs_nolink[@]}"

# ln -s -r /opt/sb/bin/clang-format-21 /opt/sb/bin/clang-format
ln -s -r /opt/sb/bin/bazelisk /opt/sb/bin/bazel
rm -rf /opt/sb/store/nettools/bin/hostname

link /opt/sb/store/s6 /opt/sb/profile/s6
link /opt/sb/store/s6-rc /opt/sb/profile/s6
link /opt/sb/store/s6-dns /opt/sb/profile/s6
link /opt/sb/store/s6-linux-init /opt/sb/profile/s6
link /opt/sb/store/s6-linux-utils /opt/sb/profile/s6
link /opt/sb/store/s6-networking /opt/sb/profile/s6
link /opt/sb/store/s6-portable-utils /opt/sb/profile/s6
link /opt/sb/store/execline /opt/sb/profile/s6

# option
rm -rf /opt/sb/store/cmake/share/cmake*/Help
rm -rf /opt/sb/store/cmake/share/doc
rm -rf /opt/sb/store/vim/share/vim/vim*/doc
rm -rf /opt/sb/store/protobuf*/lib
