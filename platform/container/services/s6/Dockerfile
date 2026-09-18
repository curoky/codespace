FROM docker.io/debian:trixie-slim

RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates curl tzdata \
  && rm -rf /var/lib/apt/lists/*

RUN --mount=type=bind,source=platform/container/services/s6/binman.yaml,target=/tmp/binman.yaml \
    curl -fsSL https://raw.githubusercontent.com/curoky/standalone-binaries/refs/heads/master/cmd/binman/install.sh \
    | bash -s -- --prefix /opt/bm/bin \
  && /opt/bm/bin/bm sync /tmp/binman.yaml

ENV PATH="/opt/bm/bin:/opt/bm/profile/s6/bin:/opt/bm/profile/s6/libexec:$PATH"

COPY platform/container/workspace/rootfs/etc/s6/skel/ /etc/s6/skel/
COPY platform/container/workspace/scripts/install-s6.sh /etc/s6/install-s6.sh
COPY platform/container/services/s6/rootfs/ /

RUN /etc/s6/install-s6.sh

ENTRYPOINT ["/etc/s6/init/bin/init"]
