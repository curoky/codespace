#!/usr/bin/env bash
set -xeuo pipefail

userdel ubuntu -r || echo "ignore userdel failed"

echo "root:x123456" | chpasswd

useradd --create-home --uid 5230 --user-group x
echo "x:x123456" | chpasswd
usermod -aG sudo x

chown -R 5230:5230 /home/x

install -d -o 5230 -g 5230 -m 0700 /home/x/.ssh
install -d -m 0700 /var/lib/codespace

echo "/opt/bm/bin/zsh" >>/etc/shells
chsh -s /opt/bm/bin/zsh root
chsh -s /opt/bm/bin/zsh x

useradd --uid 200 -g 65534 --home-dir /run/sshd --create-home --shell /usr/sbin/nologin sshd
mkdir -p /var/empty
# Git cannot preserve the modes required by sshd and sudo.
chmod 600 /etc/ssh/ssh_host_*_key
chmod 440 /etc/sudoers /etc/sudoers.d/more_secure_path /etc/sudoers.d/nopasswd_user

chown root:root /opt/bm/store/sudo/bin/sudo
chmod u+s /opt/bm/store/sudo/bin/sudo

ln -sf /usr/share/zoneinfo/Asia/Singapore /etc/localtime

# User x has no CAP_SYS_ADMIN; mutate the store target because the profile entry
# for the required setuid fusermount3 helper is a symlink.
chown root:root /opt/bm/store/fuse3/bin/fusermount3
chmod u+s /opt/bm/store/fuse3/bin/fusermount3

install -d /etc/ssl/certs
cp /opt/bm/etc/ssl/certs/ca-bundle.crt /etc/ssl/certs/ca-certificates.crt

install -d /usr/lib/locale
cp /opt/bm/lib/locale/locale-archive /usr/lib/locale/locale-archive

ln -s /opt/bm/store/zsh/bin/zsh /usr/bin
ln -s /opt/bm/store/wget/bin/wget /usr/bin
ln -s /opt/bm/store/less/bin/less /usr/bin
ln -s /opt/bm/store/xz/bin/xz /usr/bin
ln -s /opt/bm/store/git/bin/git /usr/bin
ln -s /opt/bm/store/openssh_gssapi/bin/ssh /usr/bin
