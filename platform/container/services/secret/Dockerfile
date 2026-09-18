FROM ghcr.io/curoky/codespace:service-s6

RUN /opt/bm/bin/bm install rclone

COPY platform/container/services/secret/rootfs/ /
RUN chmod +x /opt/secret/serve.sh \
  && /etc/s6/install-s6.sh
