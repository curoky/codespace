FROM ghcr.io/curoky/codespace:service-s6

RUN apt-get update -y \
  && apt-get install -y --no-install-recommends libgomp1 \
  && rm -rf /var/lib/apt/lists/*

RUN /opt/bm/bin/bm install uv

# Python 3.12 is the newest version covered by all pinned GPU wheels.
# Dependencies span the vLLM, PyTorch and PyPI indexes, requiring best-match resolution.
ARG VLLM_COMMIT=e126687a9a828d513c01a07cd69f025f27d63280
ARG CUDA_TAG=cu129
RUN /opt/bm/bin/uv venv /opt/vllm/venv --python 3.12 \
  && /opt/bm/bin/uv pip install --python /opt/vllm/venv/bin/python \
    --prerelease=allow \
    --index-strategy unsafe-best-match \
    vllm \
    --extra-index-url "https://wheels.vllm.ai/${VLLM_COMMIT}" \
    --extra-index-url "https://download.pytorch.org/whl/${CUDA_TAG}"

ENV PATH="/opt/vllm/venv/bin:$PATH"

COPY platform/container/services/vllm/rootfs/ /
RUN /etc/s6/install-s6.sh
