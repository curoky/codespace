FROM docker.io/debian:trixie-slim

RUN apt-get update -y \
  && apt-get install -y --no-install-recommends bash ca-certificates curl zstd \
  && rm -rf /var/lib/apt/lists/*

COPY codespace/sidecar/sb-pkgs.yaml /tmp/sb-pkgs.yaml
RUN curl -fsSL https://raw.githubusercontent.com/curoky/standalone-binaries/refs/heads/master/client/install.sh \
    | bash -s -- --prefix /opt/sb/bin \
  && /opt/sb/bin/sb sync /tmp/sb-pkgs.yaml

ENV PATH="/opt/sb/bin:/opt/sb/profile/s6/bin:/opt/sb/profile/s6/libexec:$PATH"

COPY codespace/images/dev/rootfs/etc/s6/skel /etc/s6/skel
COPY codespace/sidecar/rootfs/ /
COPY codespace/images/dev/script/setup-s6.sh /tmp/setup-s6.sh
RUN /tmp/setup-s6.sh

ENTRYPOINT ["/etc/s6/init/bin/init"]
