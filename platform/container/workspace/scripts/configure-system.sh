#!/usr/bin/env bash
set -xeuo pipefail

# Apply build-time user, permission, locale, and FUSE settings that require
# filesystem mutation.

userdel ubuntu -r || echo "ignore userdel failed"

echo "root:x123456" | chpasswd

useradd --create-home --uid 5230 --user-group x
echo "x:x123456" | chpasswd
usermod -aG sudo x
echo "x ALL=(ALL:ALL) NOPASSWD:ALL" >>/etc/sudoers.d/nopasswd_user

install -d -o 5230 -g 5230 -m 0700 /home/x/.ssh

echo "/opt/bm/bin/zsh" >>/etc/shells
chsh -s /opt/bm/bin/zsh root
chsh -s /opt/bm/bin/zsh x

useradd --uid 200 -g 65534 --home-dir /run/sshd --create-home --shell /usr/sbin/nologin sshd
mkdir -p /var/empty
# Host keys are shipped under /etc/ssh, but Git cannot preserve the
# 0600 mode, so tighten the private keys here at build time; sshd refuses to
# start with world-readable host keys.
chmod 600 /etc/ssh/ssh_host_*_key

# sudoers drop-in shipped via rootfs; Git cannot preserve the 0440 mode sudo
# requires, so tighten it here at build time.
chmod 440 /etc/sudoers.d/more_secure_path

ln -sf /usr/share/zoneinfo/Asia/Singapore /etc/localtime

echo "en_US.UTF-8 UTF-8" >/etc/locale.gen
locale-gen

# gocryptfs runs as x without CAP_SYS_ADMIN, so its fusermount3 helper must be
# setuid root. Set the store target because the profile entry is a symlink.
chown root:root /opt/bm/store/fuse3/bin/fusermount3
chmod u+s /opt/bm/store/fuse3/bin/fusermount3
