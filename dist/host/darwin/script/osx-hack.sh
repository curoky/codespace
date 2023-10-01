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

# ref:
# - https://github.com/rgcr/m-cli
# - https://gist.github.com/gguerini/2513786
# - https://gist.github.com/garethrees/2470157
# - https://gist.github.com/mbinna/2357277
# - https://gist.github.com/MatthewEppelsheimer/2269385
# - https://github.com/kevinSuttle/macOS-Defaults/blob/master/.macos
# - https://github.com/MarioCatuogno/Clean-macOS/blob/master/bin/config.sh
# - https://github.com/mathiasbynens/dotfiles/blob/main/.macos
# - https://github.com/adamisntdead/DevMyMac/blob/master/setup.sh
# - https://github.com/webpro/dotfiles/blob/master/macos/defaults.sh
# - https://github.com/sqrthree/defaults-write/blob/master/README-zh.md
# - https://gist.github.com/alanzeino/42b6d983c7aa2f29d64ea2749621f7cf

# Close any open System Preferences panes, to prevent them from overriding
# settings we’re about to change
osascript -e 'tell application "System Preferences" to quit'

# Keep-alive: update existing `sudo` time stamp until `.macos` has finished
while true; do
  sudo -n true
  sleep 60
  kill -0 "$$" || exit
done 2>/dev/null &

###############################################################################
# Hostname                                                                    #
###############################################################################

# scutil --set ComputerName "$cpname"
# if [[ $(scutil --get HostName) != "OSX" ]]; then
#   scutil --set HostName "OSX"
# fi
# scutil --set LocalHostName "$cpname"
# defaults write /Library/Preferences/SystemConfiguration/com.apple.smb.server NetBIOSName -string "$cpname"

###############################################################################
# General UI/UX                                                               #
###############################################################################

echo "Set highlight color to Purple"
defaults write NSGlobalDomain AppleHighlightColor -string "0.968627 0.831373 1.000000 Purple"

echo "Sidebar icon size Biggest"
defaults write "Apple Global Domain" NSTableViewDefaultSizeMode -int 3

echo "Dock with 5*10"
defaults write com.apple.dock springboard-columns -int 10
defaults write com.apple.dock springboard-rows -int 5
defaults write com.apple.dock ResetLaunchPad -bool TRUE

## change cursose size
echo "Light tap to tap, left corner"
defaults write com.apple.AppleMultitouchTrackpad Clicking -int 1
defaults write com.apple.AppleMultitouchTrackpad TrackpadCornerSecondaryClick -int 1
defaults write com.apple.AppleMultitouchTrackpad TrackpadRightClick -bool false
defaults write com.apple.driver.AppleBluetoothMultitouch.trackpad Clicking -int 1
defaults write com.apple.driver.AppleBluetoothMultitouch.trackpad TrackpadCornerSecondaryClick -int 1
defaults write com.apple.driver.AppleBluetoothMultitouch.trackpad TrackpadRightClick -bool false

###############################################################################
# Finder                                                                      #
###############################################################################
echo "Show all filename extensions in Finder"
defaults write "Apple Global Domain" AppleShowAllExtensions -bool true
# defaults write com.apple.finder AppleShowAllFiles true
defaults write "Apple Global Domain" com.apple.keyboard.fnState -bool true
chflags nohidden ~/Library

echo "Show Status bar in Finder"
defaults write com.apple.finder ShowStatusBar -bool true

echo "Show Path bar in Finder"
defaults write com.apple.finder ShowPathbar -bool true

echo "Display full POSIX path as Finder window title"
defaults write com.apple.finder _FXShowPosixPathInTitle -bool true

# Keep folders on top when sorting by name
defaults write com.apple.finder _FXSortFoldersFirst -bool true

echo "Use current directory as default search scope in Finder"
defaults write com.apple.finder FXDefaultSearchScope -string "SCcf"

# Disable the warning when changing a file extension
defaults write com.apple.finder FXEnableExtensionChangeWarning -bool false

echo "Set Desktop as the default location for new Finder windows"
# For other paths, use `PfLo` and `file:///full/path/here/`
defaults write com.apple.finder NewWindowTarget -string "PfLo"
defaults write com.apple.finder NewWindowTargetPath -string "file://${HOME}/"

# echo "Configure macOS Screen Capture"
# mkdir $HOME/Pictures/Screenshots
# defaults write com.apple.screencapture location -string "$HOME/Pictures/Screenshots"
# defaults write com.apple.screencapture type -string "png"

###############################################################################
# Keyboard                                                                    #
###############################################################################
echo "Disable auto-correct"
defaults write NSGlobalDomain NSAutomaticSpellingCorrectionEnabled -bool false

###############################################################################
# Software Updates                                                            #
###############################################################################

# Enable the automatic update check
defaults write com.apple.SoftwareUpdate AutomaticCheckEnabled -bool true

# Check for software updates daily, not just once per week
defaults write com.apple.SoftwareUpdate ScheduleFrequency -bool true

# Download newly available updates in background
defaults write com.apple.SoftwareUpdate AutomaticDownload -bool true

# Install System data files & security updates
defaults write com.apple.SoftwareUpdate CriticalUpdateInstall -bool true

# echo "config ddddxxx.LyricsX"
# defaults write ddddxxx.LyricsX MenuBarLyricsEnabled -int 1
# defaults write ddddxxx.LyricsX LaunchAndQuitWithPlayer -bool true
# defaults write ddddxxx.LyricsX CombinedMenubarLyrics -bool true

echo "Kill affected applications"
for app in "Address Book" "Calendar" "Contacts" "Dock" "Finder" "Mail" "Safari" "SystemUIServer" "iCal"; do
  echo "kill ${app}"
  killall "${app}" &>/dev/null
done
