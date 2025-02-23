# Reference development image for the codespace scheme.
# Thin wrapper over the shared base image (images/base), which already satisfies
# the minimal container contract in codespace/DESIGN.md §3:
#   1. sshd listens on container port 22 (public-key auth, no passwords).
#   2. A non-root login user `x` with a writable home and ~/.ssh.
#   3. A `/workspace` mount point writable by `x`.
#   4. git and an ssh client available.
# The base image runs sshd under s6 (ENTRYPOINT /etc/s6/init/bin/init) and reads
# each login user's ~/.ssh/authorized_keys, so the agent's runtime key injection
# (podman put_archive) works without any codespace-specific hooks in the image.

FROM ghcr.io/curoky/devspace:base-debian12
