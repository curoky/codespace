#!/usr/bin/env bash

# Set up s6 as the container init using the binaries already compiled under
# /opt/sb/store/s6*. install-sb-pkgs.sh merges every s6 / execline package
# into the /opt/sb/profile/s6 tree (bin/ + libexec/), which is what we put on
# the init's PATH.
#
# All s6 configuration (s6-rc service definitions, the s6-linux-init skel, and
# helper scripts) lives in dotfiles/s6 and is copied to /etc/s6 by
# setup-sysconf.sh. This script must run after that copy: it only compiles the
# s6-rc database and generates the container init from the skel.

set -xeuo pipefail

profile=/opt/sb/profile/s6
# s6-rc resolves s6-rc-oneshot-run / s6-rc-fdholder-filler through PATH.
export PATH="$profile/bin:$profile/libexec:$PATH"

# Compile the s6-rc database at build time, so rc.init only has to run
# s6-rc-init at boot (matching the upstream s6-linux-init template).
rm -rf /etc/s6/db
s6-rc-compile /etc/s6/db /etc/s6/s6-rc.d

# Note: s6-rc-compile emits its internal oneshot / fdholder run scripts with a
# "#!/usr/bin/env -S execlineb -P" shebang. The "-S" (so Debian 10's /usr/bin/env
# splits the interpreter from its options) is baked in at build time via the
# execline package's EXECLINE_SHEBANGPREFIX (packages/execline/default.nix), so
# no post-compile shebang rewrite is needed here.

# Generate the container init (stage 1). At boot bin/init copies run-image into
# /run (creating /run/service and /run/s6), dumps the container environment to
# /run/s6/container_environment (-s), starts s6-svscan, and runs scripts/rc.init
# (stage 2), which brings up the services.
# -C: container mode (SIGTERM -> orderly shutdown, no runlevel service, sync
#     with the container manager, rc.init always gets the "user" runlevel).
# -N: do not mount/unmount/remount /run. Docker already gives us a writable
#     /run, and an unprivileged container has no CAP_SYS_ADMIN to mount a tmpfs;
#     init still *writes* run-image, /run/service and the env dump into it.
# -c is the run-time basedir: stage 1 reads its read-only data (run-image, env,
#     scripts) from there, so it must equal the generated dir (no separate copy
#     step).
rm -rf /etc/s6/init
"$profile/bin/s6-linux-init-maker" \
  -C \
  -N \
  -V 2 \
  -B \
  -c /etc/s6/init \
  -D user \
  -p "$profile/bin:$profile/libexec:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
  -s /run/s6/container_environment \
  -f /etc/s6/skel \
  /etc/s6/init

# Note: s6-linux-init-maker no longer bakes any /nix/store path into the
# generated init. execline's EXECLINE_EXTBINPREFIX (foreground/fdmove/eltest/...)
# and EXECLINE_SHEBANGPREFIX are patched at build time (packages/execline via
# packages/s6-linux-init), so the generated scripts reference execline tools by
# bare name (resolved via the -p PATH) and use a "#!/usr/bin/env -S execlineb"
# shebang. No post-generation /nix/store rewrite is needed here.

# The generated bin/init invokes "s6-linux-init" by bare name, relying on PATH.
# But bin/init is the container ENTRYPOINT, so at exec time PATH does not yet
# contain the s6 profile and the binary is not found. Rewrite that one call to
# an absolute path; everything s6-linux-init starts afterwards (s6-svscan,
# rc.init, ...) finds its tools through the -p PATH baked above.
sed -i "s|s6-linux-init |$profile/bin/s6-linux-init |" /etc/s6/init/bin/init

# The env dump dir (-s /run/s6/container_environment) lives under /run/s6, but
# the maker's run-image does not contain an "s6" directory, so at boot the dump
# fails with "No such file or directory" (fatal under -N). Inject s6/ into
# run-image: stage 1 copies run-image/* into /run, so /run/s6 then exists.
mkdir -p /etc/s6/init/run-image/s6
