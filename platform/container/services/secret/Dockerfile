FROM ghcr.io/curoky/codespace:service-s6

USER x
RUN /opt/bm/bin/bm install rclone

USER root
COPY platform/container/services/secret/rootfs/ /
RUN install -d -o x -g x -m 0700 /opt/secret \
  && /etc/s6/install-s6.sh
