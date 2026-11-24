#!/usr/bin/env bash
set -euo pipefail

macos_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

if [[ ! -x /opt/homebrew/bin/brew ]]; then
  installer="/tmp/homebrew-install.sh"
  curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh \
    -o "$installer"
  NONINTERACTIVE=1 /bin/bash "$installer"
fi

export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$PATH"
/opt/homebrew/bin/brew bundle \
  --force \
  --force-cleanup \
  --file "$macos_dir/Brewfile" \
  --verbose
/opt/homebrew/bin/brew cleanup --prune=all

# Homebrew suffixes GNU GCC commands to avoid replacing Apple's compiler.
test -x /opt/homebrew/opt/gcc/bin/gcc-16
test -x /opt/homebrew/opt/gcc/bin/g++-16
install -d "$HOME/.local/bin"
ln -sfn /opt/homebrew/opt/gcc/bin/gcc-16 "$HOME/.local/bin/gcc"
ln -sfn /opt/homebrew/opt/gcc/bin/g++-16 "$HOME/.local/bin/g++"
