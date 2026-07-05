# Agent image for the codespace scheme. s6 manages the FastAPI service that
# talks to the host podman service over the mounted podman socket (PoP), plus
# the embedded atuin sync server. The image needs NO podman CLI -- podman-py
# speaks the socket directly.
#
# Build from the repo root so pyproject.toml/uv.lock are in the context:
#   podman build -t codespace/agent:latest -f codespace/images/agent/Dockerfile .

FROM docker.io/python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
  UV_LINK_MODE=copy \
  UV_PYTHON_DOWNLOADS=never

RUN apt-get update -y \
  && apt-get install -y --no-install-recommends bash ca-certificates curl zstd \
  && rm -rf /var/lib/apt/lists/*

# Install uv and the standalone-binaries packages directly in the final image;
# the agent image is small enough that a separate sb build stage is unnecessary.
RUN python -m pip install --no-cache-dir uv
COPY codespace/images/agent/sb-pkgs.yaml /tmp/sb-pkgs.yaml
RUN curl -fsSL https://raw.githubusercontent.com/curoky/standalone-binaries/refs/heads/master/client/install.sh \
    | bash -s -- --prefix /opt/sb/bin \
  && /opt/sb/bin/sb sync /tmp/sb-pkgs.yaml

ENV SSL_CERT_FILE=/opt/sb/store/cacert/etc/ssl/certs/ca-certificates.crt

WORKDIR /app

# Install exactly the locked runtime dependencies (no dev group, and without
# building this project itself -- it has no build backend, so we run it from
# source on PYTHONPATH below). uv.lock keeps the image reproducible and in sync
# with the rest of the toolchain.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy the codespace package and run it from the synced virtualenv.
COPY codespace /app/codespace
ENV PATH="/app/.venv/bin:/opt/sb/bin:/opt/sb/profile/s6/bin:/opt/sb/profile/s6/libexec:$PATH"

# Reuse the shared s6 Linux init skeleton, but compile an agent-only s6-rc
# database so the image only supervises agent-service and atuin-service.
COPY codespace/images/dev/rootfs/etc/s6/skel /etc/s6/skel
COPY codespace/images/agent/rootfs/etc/s6/s6-rc.d /etc/s6/s6-rc.d
# Reuse the dev image's atuin service definition directly so the two images do
# not maintain duplicate run scripts.
COPY codespace/images/dev/rootfs/etc/s6/s6-rc.d/atuin-service /etc/s6/s6-rc.d/atuin-service
COPY codespace/images/dev/script/setup-s6.sh /tmp/setup-s6.sh
RUN /tmp/setup-s6.sh

# The agent is stateless; services read configuration from the container
# environment dumped by s6-linux-init (see run.sh).
ENTRYPOINT ["/etc/s6/init/bin/init"]
