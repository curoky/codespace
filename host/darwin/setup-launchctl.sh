#!/usr/bin/env bash
set -xeuo pipefail

launchctl bootout gui/"$(id -u)"/sh.atuin.daemon || true
launchctl bootstrap gui/"$(id -u)" ~/Library/LaunchAgents/sh.atuin.daemon.plist
launchctl kickstart -k gui/"$(id -u)"/sh.atuin.daemon

# launchctl bootout gui/"$(id -u)"/sh.atuin.server || true
# launchctl bootstrap gui/"$(id -u)" ~/Library/LaunchAgents/sh.atuin.server.plist
# launchctl kickstart -k gui/"$(id -u)"/sh.atuin.server
