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

chown -R 5230:5230 /home/x
chmod 700 /home/x/.ssh
chmod 600 /home/x/.ssh/authorized_keys /home/x/.ssh/config /home/x/.ssh/known_hosts

# change login shell
echo "/opt/bm/bin/zsh" >>/etc/shells
chsh -s /opt/bm/bin/zsh root
chsh -s /opt/bm/bin/zsh x

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

# setup locales from apt
echo "en_US.UTF-8 UTF-8" >/etc/locale.gen
locale-gen

# fusermount3 (binman fuse3) needs setuid root so the unprivileged user `x` can
# mount FUSE: workspace-init runs gocryptfs as `x` (so ciphertext files land
# owned by 5230:5230), which lacks CAP_SYS_ADMIN, and the binman static build
# ships fusermount3 without the setuid bit. Without this, gocryptfs mount fails
# with "fusermount3: mount failed: Operation not permitted" and sshd (which
# depends on workspace-init) never
# starts. Set on the store target since /opt/bm/bin/fusermount3 is a symlink.
chown root:root /opt/bm/store/fuse3/bin/fusermount3
chmod u+s /opt/bm/store/fuse3/bin/fusermount3
