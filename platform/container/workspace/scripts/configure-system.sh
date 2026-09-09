#!/usr/bin/env bash
set -xeuo pipefail

# Apply build-time user, permission, locale, and FUSE settings that require
# filesystem mutation.

userdel ubuntu -r || echo "ignore userdel failed"

echo "root:x123456" | chpasswd

useradd --create-home --uid 5230 --user-group x
echo "x:x123456" | chpasswd
usermod -aG sudo x

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

# sudoers shipped via rootfs; Git cannot preserve the 0440 mode sudo requires,
# so tighten the main file and drop-in here at build time.
chmod 440 /etc/sudoers /etc/sudoers.d/more_secure_path /etc/sudoers.d/nopasswd_user

# sudo now comes from /opt/bm instead of apt, so set it setuid-root on the store
# target (the profile entry is a symlink).
chown root:root /opt/bm/store/sudo/bin/sudo
chmod u+s /opt/bm/store/sudo/bin/sudo

ln -sf /usr/share/zoneinfo/Asia/Singapore /etc/localtime

echo "en_US.UTF-8 UTF-8" >/etc/locale.gen
locale-gen

# gocryptfs runs as x without CAP_SYS_ADMIN, so its fusermount3 helper must be
# setuid root. Set the store target because the profile entry is a symlink.
chown root:root /opt/bm/store/fuse3/bin/fusermount3
chmod u+s /opt/bm/store/fuse3/bin/fusermount3

# CA bundle now comes from /opt/bm (binman cacert) instead of apt
# ca-certificates; point the Debian default path at it so consumers that read
# the fixed location (openssl, curl, git, wget, python) resolve trust anchors.
install -d /etc/ssl/certs
ln -sf /opt/bm/etc/ssl/certs/ca-bundle.crt /etc/ssl/certs/ca-certificates.crt

# Expose selected static tools under /usr/bin for consumers that do not inherit
# /opt/bm/bin on PATH (sshd, sudo secure_path, git subprocess).
ln -s /opt/bm/store/zsh/bin/zsh /usr/bin
ln -s /opt/bm/store/wget/bin/wget /usr/bin
ln -s /opt/bm/store/less/bin/less /usr/bin
ln -s /opt/bm/store/xz/bin/xz /usr/bin
ln -s /opt/bm/store/git/bin/git /usr/bin
ln -s /opt/bm/store/openssh_gssapi/bin/ssh /usr/bin
