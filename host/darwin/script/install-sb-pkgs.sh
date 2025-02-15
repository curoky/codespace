#!/usr/bin/env bash

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
  smartmontools
  cloc
  parallel
  exiftool
  wget
  prettier
  pnpm

  # lxgw-wenkai
  # fira-code
  # nerd-fonts.fira-code
  # nerd-fonts.ubuntu-mono

  ##### unneeded
  # vim
  # zsh
  # aria2
  # gost

)

# Installed but not linked into bin (avoid exposing their binaries).
nolink_pkgs=(
  nodejs-slim26
  perl
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

# nodejs-slim26 is installed but not linked into bin (avoid exposing its node/npm).
/opt/sb/bin/sb install --prefix /opt/sb --link=false "${nolink_pkgs[@]}"

ln -sf /opt/sb/bin/bazelisk /opt/sb/bin/bazel
