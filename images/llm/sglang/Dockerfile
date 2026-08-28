# Qwen3.8-Flash-Next-FP8 serving image (SGLang engine).
#
# Base image and assembly aligned with images/sidecar/Dockerfile: debian:trixie-slim
# with binman-installed standalone s6/execline as PID 1 and services under
# rootfs/etc/s6/s6-rc.d.
#
# Unlike the sidecar, this image ships the full CUDA + inference stack itself
# (Debian has no CUDA runtime and no SGLang). The ~172 GiB FP8 weights are NOT
# baked in; they are resolved at run time from a bind-mounted Hugging Face cache.
#
# WARNING (day-0 architecture): the stable PyPI SGLang may not yet include the
# Qwen3.8-Flash-Next architecture. Pin SGLANG_VERSION to a build that does (the
# official cookbook uses a dedicated tag / nightly). If startup fails with an
# unknown-architecture error, bump SGLANG_VERSION. This is a CUDA build; do not
# use it for AMD GPUs (use the official ROCm image instead).
FROM docker.io/debian:trixie-slim

# CUDA userspace runtime is provided by the NVIDIA Container Toolkit at run time
# (mounted from the host driver); the image only needs Python, the CUDA runtime
# libraries pulled in by the SGLang wheel, and basic tooling.
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends \
    bash ca-certificates curl tzdata zstd python3 python3-venv libgomp1 \
  && rm -rf /var/lib/apt/lists/*

COPY images/llm/sglang/binman.yaml /tmp/binman.yaml
RUN curl -fsSL https://raw.githubusercontent.com/curoky/standalone-binaries/refs/heads/master/cmd/binman/install.sh \
    | bash -s -- --prefix /opt/bm/bin \
  && /opt/bm/bin/bm sync /tmp/binman.yaml

# Inference stack installed into a dedicated venv via uv (installed by binman).
# Python 3.12 is the newest version the GPU inference stack supports: the SGLang
# GPU wheel and its flashinfer/xformers deps only ship prebuilt wheels up to
# 3.12; 3.13 fails to build.
#
# SGLANG_VERSION pins the current stable release; bump it to a build that carries
# the Qwen3.8-Flash-Next architecture.
#
# CUDA 12 install (target 8x H100 runs driver 535 / CUDA 12.2, not the CUDA 13
# default): follow the official SGLang cu129 recipe. --prerelease=allow is
# required because some SGLang deps only publish pre-releases on PyPI; without it
# uv silently resolves an older SGLang. After installing sglang, force-reinstall
# torch and the sgl-kernel / sgl-deep-gemm GPU kernels from the cu129 indexes so
# they match the CUDA 12.x driver instead of the cu13 PyPI defaults. Override
# CUDA_TAG=cu130 for a CUDA 13 host.
ARG SGLANG_VERSION=0.5.18
ARG CUDA_TAG=cu129
ENV LLM_VENV=/opt/llm/venv
RUN /opt/bm/bin/uv venv "${LLM_VENV}" --python 3.12 \
  && LLM_UV="/opt/bm/bin/uv pip install --python ${LLM_VENV}/bin/python" \
  && ${LLM_UV} --prerelease=allow "sglang==${SGLANG_VERSION}" \
  && ${LLM_UV} --force-reinstall torch torchvision torchaudio \
       --index-url "https://download.pytorch.org/whl/${CUDA_TAG}" \
  && ${LLM_UV} --force-reinstall sgl-kernel \
       --index-url "https://docs.sglang.ai/whl/${CUDA_TAG}/" \
  && ${LLM_UV} --force-reinstall sgl-deep-gemm --no-deps \
       --index-url "https://docs.sglang.ai/whl/${CUDA_TAG}/"

ENV PATH="/opt/llm/venv/bin:/opt/bm/bin:/opt/bm/profile/s6/bin:/opt/bm/profile/s6/libexec:$PATH"

COPY images/dev/rootfs/etc/s6/skel /etc/s6/skel
COPY images/llm/sglang/rootfs/ /
RUN chmod +x /opt/llm/serve.sh
COPY images/dev/script/setup-s6.sh /tmp/setup-s6.sh
RUN /tmp/setup-s6.sh

ENTRYPOINT ["/etc/s6/init/bin/init"]
