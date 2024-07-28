#!/usr/bin/env bash
set -xeuo pipefail

# ollama
mkdir -p /etc/s6-overlay/s6-rc.d/ollama
echo "longrun" >/etc/s6-overlay/s6-rc.d/ollama/type
cp /opt/devspace/images/base/script/s6-init/ollama.sh /etc/s6-overlay/s6-rc.d/ollama/run

# sshd
mkdir -p /etc/s6-overlay/s6-rc.d/sshd
echo "longrun" >/etc/s6-overlay/s6-rc.d/sshd/type
cp /opt/devspace/images/base/script/s6-init/sshd.sh /etc/s6-overlay/s6-rc.d/sshd/run

# oncetask
mkdir -p /etc/s6-overlay/s6-rc.d/oncetask
echo "oneshot" >/etc/s6-overlay/s6-rc.d/oncetask/type
cp /opt/devspace/images/base/script/s6-init/oncetask.sh /etc/s6-overlay/s6-rc.d/oncetask/up

# user
touch /etc/s6-overlay/s6-rc.d/user/contents.d/ollama
touch /etc/s6-overlay/s6-rc.d/user/contents.d/sshd
touch /etc/s6-overlay/s6-rc.d/user/contents.d/oncetask
