#!/usr/bin/env bash
set -xeuo pipefail

userdel ubuntu -r || echo "ignore userdel failed"

usermod --lock root
useradd --no-create-home --uid 5230 --user-group --shell /usr/local/bin/zsh x
passwd -d x
usermod -aG sudo x

useradd --uid 200 -g 65534 --home-dir /run/sshd --create-home --shell /usr/sbin/nologin sshd
mkdir -p /var/empty

chmod 4755 \
  /usr/local/store/fuse3/bin/fusermount3 \
  /usr/local/store/shadow/bin/newgidmap \
  /usr/local/store/shadow/bin/newuidmap \
  /usr/local/store/sudo/bin/sudo

install -d -o 5230 -g 5230 -m 0700 /opt/secret
chown -R 5230:5230 /home/x /opt
chmod 0700 /home/x/.ssh
chmod 0600 /etc/ssh/ssh_host_*_key
chmod 0440 /etc/sudoers
