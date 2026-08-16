ARG BASE_IMAGE=ghcr.io/curoky/codespace:workspace-ubuntu26.04
FROM ${BASE_IMAGE}

USER root

COPY platform/wsl/rootfs/ /

RUN /opt/bm/profile/s6/bin/s6-rc-compile /etc/s6/db.new /etc/s6/s6-rc.d \
  && rm -rf /etc/s6/db \
  && mv /etc/s6/db.new /etc/s6/db
