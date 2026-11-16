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
