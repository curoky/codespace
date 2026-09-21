#!/usr/bin/env bash
set -xeuo pipefail

userdel ubuntu -r || echo "ignore userdel failed"

usermod --lock root
useradd --no-create-home --uid 5230 --user-group --shell /usr/local/bin/zsh x
usermod --lock x
usermod -aG sudo x

echo "/usr/local/bin/zsh" >>/etc/shells

useradd --uid 200 -g 65534 --home-dir /run/sshd --create-home --shell /usr/sbin/nologin sshd
mkdir -p /var/empty
ln -sf /usr/share/zoneinfo/Asia/Singapore /etc/localtime

install -d -o 5230 -g 5230 -m 0755 /opt/bm /opt/bm/bin /opt/podman
install -d -o 5230 -g 5230 -m 0700 /opt/secret /workspace /workspace.enc /upload
install -d -o 5230 -g 5230 -m 0700 /opt/podman/data /opt/podman/data/networks
install -d -o 5230 -g 5230 -m 0700 \
  /home/x/{.vscode-server,.trae,.trae-cn,.trae-server,.trae-cn-server}/{bin,extensions}
chown -R 5230:5230 /home/x
chown 5230:5230 \
  /opt \
  /opt/bm \
  /opt/bm/bin \
  /opt/bm/bin/bm \
  /opt/podman \
  /opt/podman/data \
  /opt/podman/data/.gitkeep \
  /opt/podman/data/networks \
  /opt/secret
chmod 0700 \
  /home/x/.ssh \
  /opt/secret \
  /opt/podman/data
chmod 0600 /etc/ssh/ssh_host_*_key
chmod 0440 /etc/sudoers
chmod 0755 /usr/local/codespace/bin/* /usr/local/bin/podman /usr/local/bin/podman-server
chmod 0755 /opt/bm/bin/bm
rm -f /usr/local/bin/docker
ln -s podman /usr/local/bin/docker

# FUSE and rootless Podman require the package executables themselves to be
# setuid; BM preserves ownership but the published artifacts use mode 0755.
chmod 4755 \
  /usr/local/store/fuse3/bin/fusermount3 \
  /usr/local/store/shadow/bin/newgidmap \
  /usr/local/store/shadow/bin/newuidmap \
  /usr/local/store/sudo/bin/sudo
