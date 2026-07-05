FROM docker.io/debian:trixie-slim

RUN apt-get update -y \
  && apt-get install -y --no-install-recommends bash ca-certificates curl zstd \
  && rm -rf /var/lib/apt/lists/*

COPY codespace/images/agent/sb-pkgs.yaml /tmp/sb-pkgs.yaml
RUN curl -fsSL https://raw.githubusercontent.com/curoky/standalone-binaries/refs/heads/master/client/install.sh \
    | bash -s -- --prefix /opt/sb/bin \
  && /opt/sb/bin/sb sync /tmp/sb-pkgs.yaml


WORKDIR /app

ENV PATH="/app/.venv/bin:/opt/sb/bin:/opt/sb/profile/s6/bin:/opt/sb/profile/s6/libexec:$PATH" \
  UV_LINK_MODE=copy \
  UV_PYTHON_DOWNLOADS=managed \
  UV_PYTHON=3.13 \
  PYTHONUNBUFFERED=1 \
  PYTHONPATH=/app

COPY pyproject.toml uv.lock ./
COPY codespace /app/codespace
RUN uv python install 3.13
RUN uv sync --frozen --no-dev --no-install-project

COPY codespace/images/dev/rootfs/etc/s6/skel /etc/s6/skel
COPY codespace/images/agent/rootfs/etc/s6/s6-rc.d /etc/s6/s6-rc.d
COPY codespace/images/dev/rootfs/etc/s6/s6-rc.d/atuin-service /etc/s6/s6-rc.d/atuin-service
COPY codespace/images/dev/script/setup-s6.sh /tmp/setup-s6.sh
RUN /tmp/setup-s6.sh

ENTRYPOINT ["/etc/s6/init/bin/init"]
