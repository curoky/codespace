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

COPY --chown=x:x platform/container/services/asr/models/firered-llm/pyproject.toml platform/container/services/asr/models/firered-llm/uv.lock platform/container/services/asr/models/firered-llm/.python-version /opt/asr/models/firered-llm/
COPY --chown=x:x platform/container/services/asr/models/firered-punc/pyproject.toml platform/container/services/asr/models/firered-punc/uv.lock platform/container/services/asr/models/firered-punc/.python-version /opt/asr/models/firered-punc/
COPY --chown=x:x platform/container/services/asr/models/firered-vad/pyproject.toml platform/container/services/asr/models/firered-vad/uv.lock platform/container/services/asr/models/firered-vad/.python-version /opt/asr/models/firered-vad/
COPY --chown=x:x platform/container/services/asr/models/moss-audio/pyproject.toml platform/container/services/asr/models/moss-audio/uv.lock platform/container/services/asr/models/moss-audio/.python-version /opt/asr/models/moss-audio/
COPY --chown=x:x platform/container/services/asr/models/moss-td/pyproject.toml platform/container/services/asr/models/moss-td/uv.lock platform/container/services/asr/models/moss-td/.python-version /opt/asr/models/moss-td/
COPY --chown=x:x platform/container/services/asr/models/nemotron-diarization/pyproject.toml platform/container/services/asr/models/nemotron-diarization/uv.lock platform/container/services/asr/models/nemotron-diarization/.python-version /opt/asr/models/nemotron-diarization/
COPY --chown=x:x platform/container/services/asr/models/paraformer/pyproject.toml platform/container/services/asr/models/paraformer/uv.lock platform/container/services/asr/models/paraformer/.python-version /opt/asr/models/paraformer/
COPY --chown=x:x platform/container/services/asr/models/pyannote-community-1/pyproject.toml platform/container/services/asr/models/pyannote-community-1/uv.lock platform/container/services/asr/models/pyannote-community-1/.python-version /opt/asr/models/pyannote-community-1/
COPY --chown=x:x platform/container/services/asr/models/qwen3-aligner/pyproject.toml platform/container/services/asr/models/qwen3-aligner/uv.lock platform/container/services/asr/models/qwen3-aligner/.python-version /opt/asr/models/qwen3-aligner/
COPY --chown=x:x platform/container/services/asr/models/qwen3-asr-1.7b/pyproject.toml platform/container/services/asr/models/qwen3-asr-1.7b/uv.lock platform/container/services/asr/models/qwen3-asr-1.7b/.python-version /opt/asr/models/qwen3-asr-1.7b/
COPY --chown=x:x platform/container/services/asr/models/runtime/pyproject.toml platform/container/services/asr/models/runtime/uv.lock platform/container/services/asr/models/runtime/.python-version /opt/asr/models/runtime/
COPY --chown=x:x platform/container/services/asr/models/sensevoice/pyproject.toml platform/container/services/asr/models/sensevoice/uv.lock platform/container/services/asr/models/sensevoice/.python-version /opt/asr/models/sensevoice/
COPY --chown=x:x platform/container/services/asr/models/vibevoice/pyproject.toml platform/container/services/asr/models/vibevoice/uv.lock platform/container/services/asr/models/vibevoice/.python-version /opt/asr/models/vibevoice/
COPY --chown=x:x platform/container/services/asr/models/whisper-large-v3/pyproject.toml platform/container/services/asr/models/whisper-large-v3/uv.lock platform/container/services/asr/models/whisper-large-v3/.python-version /opt/asr/models/whisper-large-v3/
COPY --chmod=0755 platform/container/services/asr/models/install-environments.sh /usr/local/bin/install-asr-model-environments

RUN rm -f /etc/s6/s6-rc.d/default/contents.d/miniserve-logs \
    /etc/s6/s6-rc.d/default/contents.d/supercronic \
  && mkdir -p /data/asr /model-data /run/asr /home/x/.cache \
  && chown x:x /data/asr /model-data /run/asr /home/x/.cache /opt/asr/models/*/


USER x
RUN export HOME=/home/x \
  && uv python install 3.12.14 \
  && /usr/local/bin/install-asr-model-environments \
  && hardlink --ignore-time --respect-xattrs --maximize /opt/asr/models/*/.venv \
  && rm -rf /home/x/.cache/uv

USER root
COPY --chown=x:x platform/container/services/asr/models/ /opt/asr/models/
COPY platform/container/services/asr/protocol.py /opt/asr/protocol.py
COPY platform/container/services/asr/models/rootfs/ /
RUN for script in /opt/asr/models/*/download_model.sh; do \
    model_dir="${script%/*}"; \
    ln -s "/model-data/${model_dir##*/}" "$model_dir/weights"; \
  done \
  && chmod 0755 /usr/local/bin/asr-start \
  && /etc/s6/install-s6.sh

EXPOSE 8000-8012
