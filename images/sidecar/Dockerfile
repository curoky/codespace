FROM docker.io/debian:trixie-slim

RUN apt-get update -y \
  && apt-get install -y --no-install-recommends bash ca-certificates curl tzdata zstd \
  && rm -rf /var/lib/apt/lists/*

COPY images/sidecar/binman.yaml /tmp/binman.yaml
RUN curl -fsSL https://raw.githubusercontent.com/curoky/standalone-binaries/refs/heads/master/cmd/binman/install.sh \
    | bash -s -- --prefix /opt/sb/bin \
  && /opt/sb/bin/bm sync /tmp/binman.yaml

ENV PATH="/opt/sb/bin:/opt/sb/profile/s6/bin:/opt/sb/profile/s6/libexec:$PATH"

COPY images/dev/rootfs/etc/s6/skel /etc/s6/skel
COPY images/sidecar/rootfs/ /
COPY images/dev/script/setup-s6.sh /tmp/setup-s6.sh
RUN /tmp/setup-s6.sh

ENTRYPOINT ["/etc/s6/init/bin/init"]
