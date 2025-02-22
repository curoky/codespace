#!/usr/bin/env bash

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
  zellij
  postgresql

  delve
  golangci-lint
  gofumpt
  gotests
  impl
  gomodifytags
  gotools
  go-tools
  go-outline

  pnpm
  prettier
  markdownlint-cli2
  # opencommit

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
  python314
  nodejs-slim24
  nodejs-slim26

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

  # vscode go tools
  gopls
  delve
  go-tools
  gofumpt
  golangci-lint
  gomodifytags
  gotests
  gotools
  impl
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

link /opt/sb/store/gopls /opt/sb/profile/go
link /opt/sb/store/delve /opt/sb/profile/go
link /opt/sb/store/go-tools /opt/sb/profile/go
link /opt/sb/store/gofumpt /opt/sb/profile/go
link /opt/sb/store/golangci-lint /opt/sb/profile/go
link /opt/sb/store/gomodifytags /opt/sb/profile/go
link /opt/sb/store/gotests /opt/sb/profile/go
link /opt/sb/store/gotools /opt/sb/profile/go
link /opt/sb/store/impl /opt/sb/profile/go

# option
rm -rf /opt/sb/store/cmake/share/cmake*/Help
rm -rf /opt/sb/store/cmake/share/doc
rm -rf /opt/sb/store/vim/share/vim/vim*/doc
rm -rf /opt/sb/store/protobuf*/lib
