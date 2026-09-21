#!/usr/bin/env bash
set -xeuo pipefail

userdel ubuntu -r || echo "ignore userdel failed"

usermod --lock root
useradd --no-create-home --uid 5230 --user-group --shell /usr/local/bin/zsh x
passwd -d x
usermod -aG sudo x

useradd --uid 200 -g 65534 --home-dir /run/sshd --create-home --shell /usr/sbin/nologin sshd
mkdir -p /var/empty

# rootfs ships the home tree (with .gitkeep placeholders); COPY resets it to
# root-owned, so only ownership and mode need fixing here. External state
# boundaries (/workspace, /workspace.enc, /opt/podman/data) are re-created and
# re-owned at runtime by the gocryptfs-workspace and podman services, so they are
# not fixed here.
# /opt/secret is the rclone FUSE mount point and must stay empty; a shipped
# placeholder would make rclone refuse to mount ("directory not empty"), so it
# is created here instead of via rootfs.
install -d -o 5230 -g 5230 -m 0700 /opt/secret
chown -R 5230:5230 /home/x /opt
chmod 0700 /home/x/.ssh
chmod 0600 /etc/ssh/ssh_host_*_key
chmod 0440 /etc/sudoers

# FUSE and rootless Podman require the package executables themselves to be
# setuid; BM preserves ownership but the published artifacts use mode 0755.
chmod 4755 \
  /usr/local/store/fuse3/bin/fusermount3 \
  /usr/local/store/shadow/bin/newgidmap \
  /usr/local/store/shadow/bin/newuidmap \
  /usr/local/store/sudo/bin/sudo
