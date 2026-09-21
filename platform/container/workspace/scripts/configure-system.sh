#!/usr/bin/env bash
set -xeuo pipefail

userdel ubuntu -r || echo "ignore userdel failed"

echo "root:x123456" | chpasswd

useradd --create-home --uid 5230 --user-group x
echo "x:x123456" | chpasswd
usermod -aG sudo x

chown -R 5230:5230 /home/x

install -d -o 5230 -g 5230 -m 0700 /home/x/.ssh

echo "/opt/bm/bin/zsh" >>/etc/shells
chsh -s /opt/bm/bin/zsh root
chsh -s /opt/bm/bin/zsh x

useradd --uid 200 -g 65534 --home-dir /run/sshd --create-home --shell /usr/sbin/nologin sshd
mkdir -p /var/empty
# Git cannot preserve the modes required by sshd and sudo.
chmod 600 /etc/ssh/ssh_host_*_key
chmod 440 /etc/sudoers /etc/sudoers.d/more_secure_path /etc/sudoers.d/nopasswd_user

install -o root -g root -m 4755 /opt/bm/store/sudo/bin/sudo /usr/bin/sudo

ln -sf /usr/share/zoneinfo/Asia/Singapore /etc/localtime

# User x has no CAP_SYS_ADMIN, so fusermount3 must be a root-owned setuid helper.
install -o root -g root -m 4755 /opt/bm/store/fuse3/bin/fusermount3 /usr/bin/fusermount3

# Rootless Podman needs root-owned setuid helpers in PATH.
install -o root -g root -m 4755 \
  /opt/bm/store/shadow/bin/newgidmap \
  /opt/bm/store/shadow/bin/newuidmap \
  /usr/bin/
chown 5230:5230 /opt/podman/data /opt/podman/conf/networks
chmod 0700 /opt/podman/data /opt/podman/conf/networks

install -d /etc/ssl/certs
cp /opt/bm/etc/ssl/certs/ca-bundle.crt /etc/ssl/certs/ca-certificates.crt

install -d /usr/lib/locale
cp /opt/bm/lib/locale/locale-archive /usr/lib/locale/locale-archive

ln -s /opt/bm/store/zsh/bin/zsh /usr/bin
ln -s /opt/bm/store/wget/bin/wget /usr/bin
ln -s /opt/bm/store/curl/bin/curl /usr/bin
ln -s /opt/bm/store/less/bin/less /usr/bin
ln -s /opt/bm/store/xz/bin/xz /usr/bin
ln -s /opt/bm/store/git/bin/git /usr/bin
ln -s /opt/bm/store/openssh_gssapi/bin/ssh /usr/bin
