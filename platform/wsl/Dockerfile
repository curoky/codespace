# WSL flavor of the Workspace image.
#
# Export drops OCI ENTRYPOINT, CMD, and ENV, so all runtime wiring must live in
# the rootfs.
ARG BASE_IMAGE=ghcr.io/curoky/codespace:workspace-ubuntu26.04
FROM ${BASE_IMAGE}

USER root

# Login shells reconstruct toolchain PATH from rootfs configuration rather than
# inherited OCI environment.
COPY platform/wsl/rootfs/ /

# Compile the overlay's `wsl` bundle into the inherited s6-rc database.
RUN /opt/bm/profile/s6/bin/s6-rc-compile /etc/s6/db.new /etc/s6/s6-rc.d \
  && rm -rf /etc/s6/db \
  && mv /etc/s6/db.new /etc/s6/db
