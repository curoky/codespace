FROM docker.io/debian:trixie-slim

RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates curl tzdata \
  && useradd --create-home --uid 5230 --user-group x \
  && rm -rf /var/lib/apt/lists/*

RUN --mount=type=bind,source=platform/container/services/s6/binman.yaml,target=/tmp/binman.yaml \
    curl -fsSL https://raw.githubusercontent.com/curoky/standalone-binaries/refs/heads/master/cmd/binman/install.sh \
    | bash -s -- --prefix /usr/local/bin \
  && /usr/local/bin/bm sync /tmp/binman.yaml \
  && find /usr/local/store -type d -exec chmod 0755 {} +

COPY platform/container/services/s6/rootfs/ /
COPY platform/container/workspace/rootfs/etc/s6/skel/ /etc/s6/skel/
COPY platform/container/workspace/rootfs/etc/s6/s6-rc.d/miniserve-logs/ /etc/s6/s6-rc.d/miniserve-logs/
COPY platform/container/workspace/rootfs/etc/s6/s6-rc.d/supercronic/ /etc/s6/s6-rc.d/supercronic/
COPY platform/container/workspace/rootfs/etc/supercronic/crontab /etc/supercronic/crontab
COPY platform/container/workspace/scripts/install-s6.sh /etc/s6/install-s6.sh

RUN /etc/s6/install-s6.sh

ENV MINISERVE_INTERFACES=0.0.0.0
ENTRYPOINT ["/etc/s6/init/bin/init"]
