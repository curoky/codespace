#!/usr/bin/env bash
set -xeuo pipefail

if [[ ! -f /opt/homebrew/bin/brew ]]; then
  export NONINTERACTIVE=1
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

eval "$(/opt/homebrew/bin/brew shellenv)"

rm -rf ~/devspace
ln -s ~/workspace/devspace ~/devspace
~/devspace/dotfiles/setup.sh

brew bundle --force --file ~/devspace/host/darwin/conf/brew/Brewfile.personal --cleanup --verbose
# brew link krb5 --force
brew cleanup --prune=all
