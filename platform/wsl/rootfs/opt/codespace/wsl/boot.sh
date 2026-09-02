#!/bin/sh

# WSL boot entrypoint, invoked as root by /etc/wsl.conf [boot] command.
#
# Why this exists instead of the image's own /etc/s6/init/bin/init:
# the Workspace image is an OCI container whose ENTRYPOINT is s6-linux-init, which
# only performs its stage-1 work when it is PID 1. Under WSL, PID 1 is always
# Microsoft's /init, so s6-linux-init would detect it is not PID 1 and exec
# into s6-linux-init-telinit (a client for an already-running init that does
# not exist here), and no service would come up. We therefore bring the s6
# supervision tree up by hand: start s6-svscan in the foreground, then load the
# s6-rc database compiled at build time and bring up the minimal `wsl` bundle.
#
# [boot] command runs asynchronously and does not block the WSL login shell, so
# running s6-svscan in the foreground here is safe (and more reliable than
# backgrounding it, which WSL's session cleanup can reap).

set -eu

profile=/opt/bm/profile/s6
export PATH="$profile/bin:$profile/libexec:/opt/bm/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# Apply the image's sysctl tuning (inotify watches, ptrace_scope). WSL has no
# systemd here to load /etc/sysctl.d, so do it explicitly; ignore failures on
# keys the WSL kernel may not expose.
sysctl -p /etc/sysctl.d/custom.conf || true

# s6-envdir in every service's run script uses the strict default: a missing
# /run/s6/container_environment makes it exit 111 and the service never starts.
# WSL performs no container-style environment dump, so create the dir (empty is
# fine) and seed only what the WSL contract needs.
mkdir -p /run/s6/container_environment /run/service

# Bind sshd to 0.0.0.0 so it is reachable from the LAN (e.g. macOS) through
# WSL port forwarding or mirrored networking. The dev image's sshd/run reads
# SSHD_BIND from this dir and defaults to 127.0.0.1 when unset.
printf '0.0.0.0' >/run/s6/container_environment/SSHD_BIND

# Bring up s6-rc once s6-svscan is ready to accept control commands, which is
# exactly the precondition s6-rc-init needs. Readiness is NOT the mere existence
# of the .s6-svscan/control FIFO (it is created early and may pre-exist); the
# reliable signal is s6-svscan's own `-d N` notification, where it writes a
# newline to fd N when ready. We start s6-svscan with -d 4 wired to a pipe and
# have this child block on the read end until that newline arrives.
rm -f /run/s6/.wsl-notify
mkfifo /run/s6/.wsl-notify
{
  # Block until s6-svscan writes its readiness newline to the pipe.
  read -r _ <"/run/s6/.wsl-notify" || true
  rm -f /run/s6/.wsl-notify
  s6-rc-init -c /etc/s6/db /run/service
  s6-rc -v2 -up change wsl
} &

# Foreground s6-svscan becomes the root of the supervision tree (a child of
# WSL's /init, not PID 1). It supervises sshd and its workspace-init dependency.
# -d 4 makes it emit the readiness notification on fd 4, redirected to the pipe.
exec 4>/run/s6/.wsl-notify
exec s6-svscan -d 4 /run/service
