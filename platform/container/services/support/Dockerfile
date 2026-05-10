FROM docker.io/debian:trixie-slim

RUN apt-get update -y \
  && apt-get install -y --no-install-recommends bash ca-certificates curl tzdata zstd \
  && rm -rf /var/lib/apt/lists/*

COPY platform/container/services/support/binman.yaml /tmp/binman.yaml
RUN curl -fsSL https://raw.githubusercontent.com/curoky/standalone-binaries/refs/heads/master/cmd/binman/install.sh \
    | bash -s -- --prefix /opt/bm/bin \
  && /opt/bm/bin/bm sync /tmp/binman.yaml

ENV PATH="/opt/bm/bin:/opt/bm/profile/s6/bin:/opt/bm/profile/s6/libexec:$PATH"

COPY platform/container/workspace/rootfs/etc/s6/skel/ /etc/s6/skel/
COPY platform/container/services/support/rootfs/ /
COPY platform/container/workspace/scripts/install-s6.sh /tmp/install-s6.sh
RUN /tmp/install-s6.sh

ENTRYPOINT ["/etc/s6/init/bin/init"]
