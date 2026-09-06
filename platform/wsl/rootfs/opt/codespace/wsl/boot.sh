#!/bin/sh

# WSL reserves PID 1 for /init, so this starts the inherited s6 graph directly.

set -eu

profile=/opt/bm/profile/s6
export PATH="$profile/bin:$profile/libexec:/opt/bm/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

sysctl -p /etc/sysctl.d/custom.conf || true

mkdir -p /run/s6/container_environment /run/service

printf 'false' >/run/s6/container_environment/CODESPACE_ENCRYPTED

# s6-svscan's fd notification is the readiness signal for s6-rc-init.
rm -f /run/s6/.wsl-notify
mkfifo /run/s6/.wsl-notify
{
  read -r _ <"/run/s6/.wsl-notify" || true
  rm -f /run/s6/.wsl-notify
  s6-rc-init -c /etc/s6/db /run/service
  s6-rc -v2 -up change wsl
} &

exec 4>/run/s6/.wsl-notify
exec s6-svscan -d 4 /run/service
