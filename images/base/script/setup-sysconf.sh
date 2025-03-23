#!/usr/bin/env bash
set -xeuo pipefail

# User provisioning + system configuration. Runs at build time before `USER x`.
# Static config files are laid down at their standard Debian/Ubuntu paths via
# `COPY rootfs/ /` in the Dockerfile; this script performs the command-only
# operations that cannot be expressed as a static file tree.

# remove user ubuntu
userdel ubuntu -r || echo "ignore userdel failed"

# update user root
echo "root:x123456" | chpasswd

# add user x
useradd --create-home --uid 5230 --user-group x
echo "x:x123456" | chpasswd
usermod -aG sudo x
echo "x ALL=(ALL:ALL) NOPASSWD:ALL" >>/etc/sudoers.d/nopasswd_user

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
