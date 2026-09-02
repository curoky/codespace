#!/usr/bin/env bash

# Compile the image's s6-rc definitions and generate its container init.
# Requires the merged s6 profile, /etc/s6/skel, and /etc/s6/s6-rc.d.

set -xeuo pipefail

profile=/opt/bm/profile/s6
# s6-rc resolves generated helper names through PATH.
export PATH="$profile/bin:$profile/libexec:$PATH"

# Compile the immutable service database at build time.
rm -rf /etc/s6/db
s6-rc-compile /etc/s6/db /etc/s6/s6-rc.d

# Container mode delegates signals to the container manager. The image supplies
# writable /run, so init must not mount its own tmpfs there.
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

# The generated bin/init invokes "s6-linux-init" by bare name, relying on PATH.
# As the container ENTRYPOINT it runs before the profile is on PATH, so make
# that first lookup absolute.
sed -i "s|s6-linux-init |$profile/bin/s6-linux-init |" /etc/s6/init/bin/init

# Stage 1 copies run-image into /run before writing the environment dump.
mkdir -p /etc/s6/init/run-image/s6
