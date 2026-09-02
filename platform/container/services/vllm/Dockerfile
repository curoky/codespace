# Qwen3.8-Flash-Next-FP8 serving image (vLLM engine).
#
# The model architecture comes from a pinned per-commit wheel. Model weights stay
# in the bind-mounted Hugging Face cache rather than the image.
FROM docker.io/debian:trixie-slim

# CUDA userspace runtime is provided by the NVIDIA Container Toolkit at run time
# (mounted from the host driver). uv builds its own CPython venv (no system
# python3 needed) and the CUDA runtime libs come from the vLLM wheels; the image
# only needs bash (serve.sh), TLS certs, curl (binman installer), zstd (binman
# unpacks .tar.zst) and libgomp1 (OpenMP runtime for torch).
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends \
    bash ca-certificates curl zstd libgomp1 \
  && rm -rf /var/lib/apt/lists/*

COPY platform/container/services/vllm/binman.yaml /tmp/binman.yaml
RUN curl -fsSL https://raw.githubusercontent.com/curoky/standalone-binaries/refs/heads/master/cmd/binman/install.sh \
    | bash -s -- --prefix /opt/bm/bin \
  && /opt/bm/bin/bm sync /tmp/binman.yaml

# Inference stack installed into a dedicated venv via uv (installed by binman).
# Python 3.12 is the newest version the GPU inference stack supports: vLLM
# nominally allows 3.10-3.13, but the prebuilt CUDA/flashinfer/xformers wheels
# only cover up to 3.12; 3.13 fails to build.
#
# The per-commit wheel uses a placeholder package version, so resolve it through
# the commit index rather than a release URL.
#
# CUDA_TAG selects the torch CUDA backend resolved from the PyTorch index. This
# source revision pins a torch build published for cu126, cu129, and cu130. The
# default target Host uses a CUDA 12 driver, so cu129 remains within the same
# major version.
#
# --index-strategy unsafe-best-match: the deps span three indexes (vLLM per-commit,
# PyTorch cu129, PyPI). uv defaults to taking each package from the FIRST index
# that lists it, which pins e.g. `packaging` to the stale copy on the PyTorch
# index (<=24.1) and then fails flashinfer-python==0.6.18's `packaging>=24.2`.
# unsafe-best-match lets uv pick the best version across all indexes instead.
ARG VLLM_COMMIT=e126687a9a828d513c01a07cd69f025f27d63280
ARG CUDA_TAG=cu129
ENV SERVE_VENV=/opt/codespace/vllm/venv
RUN /opt/bm/bin/uv venv "${SERVE_VENV}" --python 3.12 \
  && /opt/bm/bin/uv pip install --python "${SERVE_VENV}/bin/python" \
    --prerelease=allow \
    --index-strategy unsafe-best-match \
    vllm \
    --extra-index-url "https://wheels.vllm.ai/${VLLM_COMMIT}" \
    --extra-index-url "https://download.pytorch.org/whl/${CUDA_TAG}"

ENV PATH="/opt/codespace/vllm/venv/bin:/opt/bm/bin:/opt/bm/profile/s6/bin:/opt/bm/profile/s6/libexec:$PATH"

COPY platform/container/workspace/rootfs/etc/s6/skel/ /etc/s6/skel/
COPY platform/container/services/vllm/rootfs/ /
RUN chmod +x /opt/codespace/vllm/serve.sh
COPY platform/container/workspace/scripts/install-s6.sh /tmp/install-s6.sh
RUN /tmp/install-s6.sh

ENTRYPOINT ["/etc/s6/init/bin/init"]
