#!/usr/bin/env bash
set -xeuo pipefail

# System configuration files now live under images/base/rootfs and are rsync'd
# to their standard Debian/Ubuntu locations by the Dockerfile. This script only
# performs the non-file command operations that cannot be expressed as a static
# file tree.

# change login shell
echo "/opt/sb/bin/zsh" >>/etc/shells
chsh -s /opt/sb/bin/zsh root
chsh -s /opt/sb/bin/zsh x

# sshd
useradd --uid 200 -g 65534 --home-dir /run/sshd --create-home --shell /usr/sbin/nologin sshd
mkdir -p /var/empty
# Host keys are shipped under /etc/ssh (via rootfs) but git cannot preserve the
# 0600 mode, so tighten the private keys here at build time; sshd refuses to
# start with world-readable host keys.
chmod 600 /etc/ssh/ssh_host_*_key

# sudoers drop-in shipped via rootfs; git cannot preserve the 0440 mode sudo
# requires, so tighten it here at build time.
chmod 440 /etc/sudoers.d/more_secure_path

# timezone: link to the tzdata-provided zoneinfo file
ln -sf /usr/share/zoneinfo/Asia/Singapore /etc/localtime

# env and rc file
ln -s /etc/zsh/zshenv /etc/zshenv

# setup locales from apt
echo "en_US.UTF-8 UTF-8" >/etc/locale.gen
locale-gen
