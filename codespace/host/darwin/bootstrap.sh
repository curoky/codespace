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

brew bundle --force --file ~/devspace/codespace/host/darwin/Brewfile --cleanup --verbose
# brew link krb5 --force
brew cleanup --prune=all

~/devspace/codespace/host/darwin/start-podman.sh

launchctl bootout gui/"$(id -u)"/sh.atuin.daemon || true
launchctl bootstrap gui/"$(id -u)" ~/Library/LaunchAgents/sh.atuin.daemon.plist
launchctl kickstart -k gui/"$(id -u)"/sh.atuin.daemon

launchctl bootout gui/"$(id -u)"/sh.atuin.server || true
launchctl bootstrap gui/"$(id -u)" ~/Library/LaunchAgents/sh.atuin.server.plist
launchctl kickstart -k gui/"$(id -u)"/sh.atuin.server
