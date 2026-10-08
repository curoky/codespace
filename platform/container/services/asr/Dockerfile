FROM docker.io/nvidia/cuda:13.0.3-devel-ubuntu24.04@sha256:b7ae301dea2c162444795462ce17a05f6a516e5a75944b57af5b88540a1a2266 AS cuda-toolkit
SHELL ["/bin/bash", "-euo", "pipefail", "-c"]

RUN mkdir -p /opt/cuda-13.0/targets/x86_64-linux/lib/stubs \
  && cp -a /usr/local/cuda-13.0/bin /usr/local/cuda-13.0/nvvm /opt/cuda-13.0/ \
  && cp -a /usr/local/cuda-13.0/targets/x86_64-linux/include \
    /opt/cuda-13.0/targets/x86_64-linux/ \
  && cp -a \
    /usr/local/cuda-13.0/targets/x86_64-linux/lib/libcudadevrt.a \
    /usr/local/cuda-13.0/targets/x86_64-linux/lib/libcudart.so* \
    /usr/local/cuda-13.0/targets/x86_64-linux/lib/libcudart_static.a \
    /opt/cuda-13.0/targets/x86_64-linux/lib/ \
  && cp -a /usr/local/cuda-13.0/targets/x86_64-linux/lib/stubs/libcuda.so \
    /opt/cuda-13.0/targets/x86_64-linux/lib/stubs/ \
  && ln -s targets/x86_64-linux/include /opt/cuda-13.0/include \
  && ln -s targets/x86_64-linux/lib /opt/cuda-13.0/lib64

FROM ghcr.io/curoky/codespace:service-s6 AS runtime
SHELL ["/bin/bash", "-euo", "pipefail", "-c"]

COPY --from=cuda-toolkit /opt/cuda-13.0/ /usr/local/cuda-13.0/
ENV CUDA_HOME=/usr/local/cuda-13.0 \
  PATH=/usr/local/cuda-13.0/bin:${PATH}

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
COPY --chmod=0755 platform/container/services/asr/install-model-environments.sh /usr/local/bin/install-asr-model-environments
COPY platform/container/services/asr/rootfs/ /
RUN chmod 0440 /etc/sudoers.d/asr \
  && visudo -cf /etc/sudoers.d/asr \
  && chmod 0755 /usr/local/bin/asr-model-service

RUN rm -f /etc/s6/s6-rc.d/default/contents.d/miniserve-logs \
    /etc/s6/s6-rc.d/default/contents.d/supercronic \
  && mkdir -p /data/asr /model-data /run/asr \
  && for script in /opt/asr/models/*/download_model.sh; do \
    model_dir="${script%/*}"; \
    ln -s "/model-data/${model_dir##*/}" "$model_dir/weights"; \
  done \
  && chown x:x /data/asr /model-data /run/asr /opt/asr/server /opt/asr/models/*/

USER x
RUN export HOME=/home/x \
  && uv python install 3.14.7 3.12.14 \
  && /usr/local/bin/install-asr-model-environments \
  && uv sync --locked --no-dev --project /opt/asr/server \
  && hardlink --ignore-time --respect-xattrs --maximize \
    /opt/asr/models/*/.venv /opt/asr/server/.venv \
  && rm -rf /home/x/.cache/uv

USER root
RUN /etc/s6/install-s6.sh

EXPOSE 8080
