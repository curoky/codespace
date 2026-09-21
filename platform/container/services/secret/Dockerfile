FROM ghcr.io/curoky/codespace:service-s6

RUN /usr/local/bin/bm install --prefix /usr/local rclone \
  && find /usr/local/store -type d -exec chmod 0755 {} +

COPY platform/container/services/secret/rootfs/ /
RUN install -d -o x -g x -m 0700 /opt/secret \
  && /etc/s6/install-s6.sh
