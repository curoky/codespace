# WSL flavor of the dev image: FROM the dev image, overlay only WSL-specific
# assets, and recompile the s6-rc database so the new `wsl` bundle is known.
#
# Nothing here configures runtime behavior via image metadata: this image is
# consumed by `podman export | gzip > *.wsl`, which flattens the filesystem and
# DROPS ENTRYPOINT/CMD/ENV. WSL never reads OCI config either. All runtime wiring
# lives inside the rootfs (/etc/wsl.conf + /opt/wsl/boot.sh).
ARG BASE_IMAGE=ghcr.io/curoky/devspace:codespace-ubuntu26.04
FROM ${BASE_IMAGE}

USER root

# Overlay WSL-only assets: /etc/wsl.conf, /opt/wsl/boot.sh and the minimal `wsl`
# s6-rc bundle (only sshd; its workspace-init dependency is pulled in by s6-rc).
#
# Note on PATH: `docker export` drops the image ENV, so the nix/rust/conda/s6
# paths it injects are lost in the exported rootfs. They are NOT patched here --
# the dev image's /etc/zsh/zshenv adds them unconditionally (guarded by `-d`),
# and user `x`'s login shell is zsh (chsh'd at dev build time), so every WSL zsh
# session recovers the full PATH from the rootfs alone.
COPY images/wsl/rootfs/ /

# The base image's s6-rc database was compiled without the `wsl` bundle. Rebuild
# it in place so boot.sh's `s6-rc -up change wsl` resolves.
RUN /opt/sb/profile/s6/bin/s6-rc-compile /etc/s6/db.new /etc/s6/s6-rc.d \
  && rm -rf /etc/s6/db \
  && mv /etc/s6/db.new /etc/s6/db
