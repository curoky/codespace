#!/usr/bin/env bash
set -xeuo pipefail

curl -L -o /tmp/profile.sh https://github.com/curoky/devspace/raw/master/dotfiles/passkey/profile.gzip.sh

bash /tmp/profile.sh $@

# Usage
# curl -sSL https://github.com/curoky/devspace/raw/master/tools/profile-installer.sh | bash -s -- --ssl-pass-src pass:xxx
