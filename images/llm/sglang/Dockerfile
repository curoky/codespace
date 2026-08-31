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
# day-0 architecture: Qwen3.8-Flash-Next is NOT in any tagged SGLang release yet,
# so it cannot be installed from PyPI. Per the official SGLang cookbook, model
# support lives in PR #36497 and must be built from source. SGLANG_REF pins that
# PR ref; bump it (or point at a later tag) once the architecture ships in a
# release, after which the source build can revert to `uv pip install sglang`.
# This is a CUDA build; do not use it for AMD GPUs (use the official ROCm image).
FROM docker.io/debian:trixie-slim

# CUDA userspace runtime is provided by the NVIDIA Container Toolkit at run time
# (mounted from the host driver). uv builds its own CPython venv (no system
# python3 needed) and the CUDA runtime libs come from the SGLang wheels; the
# image only needs bash (serve.sh), TLS certs, curl (binman installer), git
# (clone the model-support PR), zstd (binman unpacks .tar.zst) and libgomp1
# (OpenMP runtime for torch).
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends \
    bash ca-certificates curl git zstd libgomp1 \
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
# SGLANG_REF pins the model-support source. Qwen3.8-Flash-Next has no tagged
# SGLang release, so instead of `uv pip install sglang` we clone the repo and
# check out PR #36497 (the model-support PR from the official cookbook), then
# install it editable. Bump SGLANG_REF to a later PR ref or, once the
# architecture ships in a release, a tag.
#
# CUDA 12 install (target 8x H100 runs driver 535 / CUDA 12.2, not the CUDA 13
# default): follow the official SGLang cu129 recipe (docs.sglang.io install guide
# + docker/Dockerfile torch_deps stage). After installing sglang from source,
# force-reinstall the pinned torch trio and the sglang-kernel / sgl-deep-gemm GPU
# kernels from the cu129 indexes so they match the CUDA 12.x driver instead of
# the cu13 PyPI defaults. TORCH_SPEC pins the cu129-matched torch build (the
# upstream recipe pins torch==2.13.0). For a CUDA 13 host, override
# CUDA_TAG=cu130 and TORCH_SPEC="torch torchvision torchaudio".
# SGLANG_BUILD_RUST_EXTS controls the PyO3 Rust extension crates (sglang-grpc,
# sglang-mm, sglang-server) that the source tree auto-builds via setuptools-rust.
# They need a cargo toolchain (pinned to Rust 1.90) that this slim CUDA image does
# not ship, and they only back the gRPC / multimodal / model-gateway entrypoints
# -- the OpenAI-compatible HTTP server (sglang.launch_server) does not use them.
# Default to `none` to skip cargo entirely; set `all` (and add a Rust toolchain)
# if you need those entrypoints.
ARG SGLANG_REF=pull/36497/head
ARG CUDA_TAG=cu129
ARG TORCH_SPEC="torch==2.13.0 torchvision==0.28.0 torchaudio==2.11.0"
ARG SGLANG_BUILD_RUST_EXTS=none
ENV LLM_VENV=/opt/llm/venv
RUN /opt/bm/bin/uv venv "${LLM_VENV}" --python 3.12 \
  && git clone --filter=blob:none https://github.com/sgl-project/sglang.git /opt/llm/sglang \
  && git -C /opt/llm/sglang fetch origin "${SGLANG_REF}" \
  && git -C /opt/llm/sglang checkout FETCH_HEAD \
  && LLM_UV="/opt/bm/bin/uv pip install --python ${LLM_VENV}/bin/python" \
  && SGLANG_BUILD_RUST_EXTS="${SGLANG_BUILD_RUST_EXTS}" \
       ${LLM_UV} --prerelease=allow -e /opt/llm/sglang/python \
  && ${LLM_UV} --force-reinstall ${TORCH_SPEC} \
       --index-url "https://download.pytorch.org/whl/${CUDA_TAG}" \
  && ${LLM_UV} --force-reinstall sglang-kernel \
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
