FROM ghcr.io/curoky/codespace:service-s6 AS runtime
SHELL ["/bin/bash", "-euo", "pipefail", "-c"]

RUN apt-get update \
  && apt-get install -y --no-install-recommends ffmpeg libsndfile1 libgomp1 git sudo build-essential \
  && rm -rf /var/lib/apt/lists/* \
  && /usr/local/bin/bm --prefix /usr/local install uv

# H100 on R535 needs CUDA 13's forward-compatible user-space driver.
RUN curl --fail --location --retry 3 \
    --output /tmp/cuda-compat.deb \
    https://developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64/cuda-compat-13-0_580.178.04-1_amd64.deb \
  && echo 'a6a75faa56cb81eab5d14ce017011ce34851d3f4f3af7065029fdf17ee692a40  /tmp/cuda-compat.deb' | sha256sum --check --strict \
  && dpkg-deb --extract /tmp/cuda-compat.deb / \
  && rm /tmp/cuda-compat.deb

COPY platform/container/services/asr/models/ /opt/asr/models/
COPY platform/container/services/asr/server/ /opt/asr/server/
COPY platform/container/services/asr/ops/ /opt/asr/ops/
COPY platform/container/services/asr/client/ /opt/asr/client/
COPY platform/container/services/asr/protocol.py platform/container/services/asr/AGENTS.md platform/container/services/asr/DESIGN.md /opt/asr/
COPY platform/container/services/asr/rootfs/ /
RUN chmod 0440 /etc/sudoers.d/asr \
  && visudo -cf /etc/sudoers.d/asr \
  && chmod 0755 /usr/local/bin/asr-model-service

RUN rm -f /etc/s6/s6-rc.d/default/contents.d/miniserve-logs \
    /etc/s6/s6-rc.d/default/contents.d/supercronic \
  && mkdir -p /data/asr /run/asr /opt/asr/server/.venv \
  && chown x:x /data/asr /run/asr /opt/asr/server /opt/asr/server/.venv \
  && for model_dir in /opt/asr/models/*/; do \
    mkdir -p "$model_dir/.venv" "$model_dir/weights"; \
    chown x:x "$model_dir" "$model_dir/.venv" "$model_dir/weights"; \
  done \
  && s6-setuidgid x s6-env HOME=/home/x uv python install 3.14.7 3.12.14 \
  && s6-setuidgid x s6-env HOME=/home/x uv sync --locked --no-dev --project /opt/asr/server \
  && /etc/s6/install-s6.sh

EXPOSE 8080
