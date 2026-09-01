# Qwen3.8-Flash-Next-FP8 serving image (vLLM engine).
#
# Base image and assembly aligned with images/sidecar/Dockerfile: debian:trixie-slim
# with binman-installed standalone s6/execline as PID 1 and services under
# rootfs/etc/s6/s6-rc.d.
#
# Unlike the sidecar, this image ships the full CUDA + inference stack itself
# (Debian has no CUDA runtime and no vLLM). The ~172 GiB FP8 weights are NOT baked
# in; they are resolved at run time from a bind-mounted Hugging Face cache.
#
# WARNING (day-0 architecture): the stable PyPI vLLM may not yet include the
# Qwen3.8-Flash-Next architecture. Pin VLLM_VERSION to a build that does (the
# official recipe uses a dedicated tag / nightly). If startup fails with an
# unknown-architecture error, bump VLLM_VERSION.
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

COPY images/llm/vllm/binman.yaml /tmp/binman.yaml
RUN curl -fsSL https://raw.githubusercontent.com/curoky/standalone-binaries/refs/heads/master/cmd/binman/install.sh \
    | bash -s -- --prefix /opt/bm/bin \
  && /opt/bm/bin/bm sync /tmp/binman.yaml

# Inference stack installed into a dedicated venv via uv (installed by binman).
# Python 3.12 is the newest version the GPU inference stack supports: vLLM
# nominally allows 3.10-3.13, but the prebuilt CUDA/flashinfer/xformers wheels
# only cover up to 3.12; 3.13 fails to build.
#
# VLLM_VERSION pins the current stable release; bump it (or the day-0 override
# below) to a build that carries the Qwen3.8-Flash-Next architecture.
#
# CUDA_TAG selects the CUDA build of vLLM. Since v0.20.0 the default PyPI `vllm`
# wheel (which carries the compiled vllm._C) links CUDA 13 (libcudart.so.13,
# needs host driver >=580), but the target 8x H100 node runs an older CUDA 12.x
# driver (535 / CUDA 12.2). `--torch-backend` only swaps the torch wheel, NOT the
# vllm wheel, so it alone still pulls the cu13 vllm._C and fails at import with
# `libcudart.so.13: cannot open shared object file`. We therefore install vLLM's
# CUDA-specific release wheel from GitHub (vllm-<ver>+<cuda>-...whl) and resolve
# torch from the matching PyTorch index. manylinux_2_28 + x86_64 because the LLM
# images are amd64-only. Override CUDA_TAG=cu130 for a CUDA 13 host.
ARG VLLM_VERSION=0.23.0
ARG CUDA_TAG=cu129
ENV LLM_VENV=/opt/llm/venv
RUN /opt/bm/bin/uv venv "${LLM_VENV}" --python 3.12 \
  && /opt/bm/bin/uv pip install --python "${LLM_VENV}/bin/python" \
    --index-strategy unsafe-best-match \
    "https://github.com/vllm-project/vllm/releases/download/v${VLLM_VERSION}/vllm-${VLLM_VERSION}+${CUDA_TAG}-cp38-abi3-manylinux_2_28_$(uname -m).whl" \
    --extra-index-url "https://download.pytorch.org/whl/${CUDA_TAG}"

ENV PATH="/opt/llm/venv/bin:/opt/bm/bin:/opt/bm/profile/s6/bin:/opt/bm/profile/s6/libexec:$PATH"

COPY images/dev/rootfs/etc/s6/skel /etc/s6/skel
COPY images/llm/vllm/rootfs/ /
RUN chmod +x /opt/llm/serve.sh
COPY images/dev/script/setup-s6.sh /tmp/setup-s6.sh
RUN /tmp/setup-s6.sh

ENTRYPOINT ["/etc/s6/init/bin/init"]
