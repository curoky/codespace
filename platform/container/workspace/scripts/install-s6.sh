#!/usr/bin/env bash

set -xeuo pipefail

profile=/opt/bm/profile/s6
export PATH="$profile/bin:$profile/libexec:$PATH"

rm -rf /etc/s6/db
s6-rc-compile /etc/s6/db /etc/s6/s6-rc.d

rm -rf /etc/s6/init
"$profile/bin/s6-linux-init-maker" \
  -C \
  -N \
  -V 2 \
  -B \
  -c /etc/s6/init \
  -D default \
  -p "$profile/bin:$profile/libexec:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
  -s /run/s6/container_environment \
  -f /etc/s6/skel \
  /etc/s6/init

# The generated entrypoint runs before the image PATH is available.
sed -i "s|s6-linux-init |$profile/bin/s6-linux-init |" /etc/s6/init/bin/init

mkdir -p /etc/s6/init/run-image/s6
