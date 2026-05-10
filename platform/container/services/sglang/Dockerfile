# Qwen3.8-Flash-Next-FP8 serving image (SGLang engine).
#
# Base image and assembly are aligned with the support Service: debian:trixie-slim
# with binman-installed standalone s6/execline as PID 1.
#
# Unlike support, this image ships the full CUDA + inference stack itself
# (Debian has no CUDA runtime and no SGLang). The ~172 GiB FP8 weights are NOT
# baked in; they are resolved at run time from a bind-mounted Hugging Face cache.
#
# day-0 architecture: Qwen3.8-Flash-Next is NOT in any tagged SGLang release yet,
# so it cannot be installed from PyPI. Per the official SGLang cookbook, model
# support lives in PR #36497 and must be built from source. SGLANG_REF pins that
# PR ref; bump it (or point at a later tag) once the architecture ships in a
# release, after which the source build can revert to `uv pip install sglang`.
# This is a CUDA build; do not use it for AMD GPUs (use the official ROCm image).
#
# CUDA Toolkit stage: SGLang's FP8 path pulls in sgl-deep-gemm, whose kernels are
# JIT-compiled at import time -- its find_cuda_home() asserts a real CUDA install
# with nvcc is present, otherwise `import deep_gemm` fails with
# `AssertionError: cuda_home is not None`. The NVIDIA Container Toolkit only
# injects the host *driver* (libcuda.so) at run time, and the inference wheels
# only ship the CUDA *runtime* libs -- neither provides the nvcc compiler or dev
# headers deep_gemm needs to build kernels. We pull the full toolkit from NVIDIA's
# official CUDA devel image and COPY just /usr/local/cuda-<ver> into the final
# image (no driver, no distro libs). Keep the CUDA version aligned with CUDA_TAG
# below. The devel image is ubuntu-based but the toolkit dir is OS-agnostic.
ARG CUDA_DEVEL_IMAGE=docker.io/nvidia/cuda:12.9.1-devel-ubuntu24.04
FROM ${CUDA_DEVEL_IMAGE} AS cuda
# Slim the toolkit before it is copied into the final image. The devel toolkit is
# ~7.3 GiB, dominated by ~3.7 GiB of static libraries (*.a) that deep_gemm's JIT
# never uses (it links dynamically), plus NPP image-processing libs and docs that
# are irrelevant here. Deleting them in this stage keeps the COPY layer small
# (deleting after COPY would only add a whiteout layer, not shrink the image).
# nvcc, nvvm, headers and the shared runtime/nvrtc libs deep_gemm needs stay.
ARG CUDA_HOME_DIR=/usr/local/cuda-12.9
RUN set -eux; \
  find "${CUDA_HOME_DIR}" -name '*.a' -delete; \
  rm -rf "${CUDA_HOME_DIR}"/targets/*/lib/libnpp* \
         "${CUDA_HOME_DIR}"/doc "${CUDA_HOME_DIR}"/share "${CUDA_HOME_DIR}"/src \
         "${CUDA_HOME_DIR}"/compute-sanitizer "${CUDA_HOME_DIR}"/extras \
         "${CUDA_HOME_DIR}"/compat

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

# CUDA Toolkit (nvcc + headers + build libs) copied from the official devel image
# above, for sgl-deep-gemm's JIT compilation. CUDA_HOME_DIR must match the devel
# image's CUDA version. Only the toolkit dir is copied; the run-time CUDA libs
# still come from the wheels and the host driver.
ARG CUDA_HOME_DIR=/usr/local/cuda-12.9
COPY --from=cuda "${CUDA_HOME_DIR}" "${CUDA_HOME_DIR}"
ENV CUDA_HOME="${CUDA_HOME_DIR}"
ENV PATH="${CUDA_HOME_DIR}/bin:$PATH"

COPY platform/container/services/sglang/binman.yaml /tmp/binman.yaml
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
#
# cu13 cleanup (last steps of the RUN): installing sglang (its deps request the
# cu13 flavor) and then force-reinstalling the cu129 torch trio leaves a full
# duplicate set of nvidia-*-cu13 wheels (~2 GiB under nvidia/cu13/ plus
# overlapping libs) that a driver-535 / CUDA-12 host can never load (cu13 needs
# driver >=580). We uninstall every nvidia package whose version is 13.x or whose
# name ends in _cu13 (keeping nvidia_ml_py) and delete the exclusive nvidia/cu13/
# tree. Because cu12 and cu13 co-own the cudnn/cusparselt/nccl/nvshmem dirs,
# uninstalling cu13 also deletes the shared .so files torch needs, so we then
# reinstall those four cu12 libs to repair torch (otherwise `import torch` dies
# with `libcudnn.so.9: cannot open shared object file`). torchcodec (a transitive
# sglang dep used by the multimodal ASR processors) is a non-nvidia package so it
# survives the cu13 purge, but its prebuilt libtorchcodec_core*.so link against
# `libnvrtc.so.13` -- provided only by the now-removed nvidia-cuda-nvrtc-cu13 --
# so at import time sglang logs `OSError: libnvrtc.so.13: cannot open shared
# object file` and skips those processors. Force-reinstall torchcodec from the
# cu129 index alongside the four cu12 libs so it resolves to the cu12 build that
# links `libnvrtc.so.12` and pulls nvidia-cuda-nvrtc-cu12 back in. Finally drop
# the sglang .git history (only needed to build) and assert torch still reports
# CUDA 12.x.
ARG SGLANG_REF=pull/36497/head
ARG CUDA_TAG=cu129
ARG TORCH_SPEC="torch==2.13.0 torchvision==0.28.0 torchaudio==2.11.0"
ARG SGLANG_BUILD_RUST_EXTS=none
ENV SERVE_VENV=/opt/codespace/sglang/venv
# UV_LINK_MODE=copy: uv defaults to hardlinking cached files into the venv, but
# we delete /root/.cache/uv in the same layer, so copy the files in instead to
# keep the venv self-contained after the cache is dropped.
ENV UV_LINK_MODE=copy
RUN /opt/bm/bin/uv venv "${SERVE_VENV}" --python 3.12 \
  && git clone --filter=blob:none https://github.com/sgl-project/sglang.git /opt/codespace/sglang/src \
  && git -C /opt/codespace/sglang/src fetch origin "${SGLANG_REF}" \
  && git -C /opt/codespace/sglang/src checkout FETCH_HEAD \
  && SERVE_UV="/opt/bm/bin/uv pip install --python ${SERVE_VENV}/bin/python" \
  && SGLANG_BUILD_RUST_EXTS="${SGLANG_BUILD_RUST_EXTS}" \
       ${SERVE_UV} --prerelease=allow -e /opt/codespace/sglang/src/python \
  && ${SERVE_UV} --force-reinstall ${TORCH_SPEC} \
       --index-url "https://download.pytorch.org/whl/${CUDA_TAG}" \
  && ${SERVE_UV} --force-reinstall sglang-kernel \
       --index-url "https://docs.sglang.ai/whl/${CUDA_TAG}/" \
  && ${SERVE_UV} --force-reinstall sgl-deep-gemm --no-deps \
       --index-url "https://docs.sglang.ai/whl/${CUDA_TAG}/" \
  && CU13_PKGS="$(ls -d ${SERVE_VENV}/lib/python3.12/site-packages/*.dist-info \
       | sed 's#.*/##;s/.dist-info//' \
       | awk -F- '/^nvidia/ {name=$1; ver=$2; if (ver ~ /^13\./ || name ~ /_cu13$/) print name}' \
       | grep -vE 'nvidia_ml_py')" \
  && for p in ${CU13_PKGS}; do /opt/bm/bin/uv pip uninstall --python ${SERVE_VENV}/bin/python "$p"; done \
  && rm -rf ${SERVE_VENV}/lib/python3.12/site-packages/nvidia/cu13 \
  && ${SERVE_UV} --reinstall --index-url "https://download.pytorch.org/whl/${CUDA_TAG}" \
       nvidia-cudnn-cu12 nvidia-cusparselt-cu12 nvidia-nccl-cu12 nvidia-nvshmem-cu12 \
       torchcodec \
  && rm -rf /opt/codespace/sglang/src/.git \
  && ${SERVE_VENV}/bin/python -c "import torch; assert torch.version.cuda.startswith('12'), torch.version.cuda" \
  && ${SERVE_VENV}/bin/python -c "import torchcodec.decoders" \
  && rm -rf /root/.cache/uv

ENV PATH="/opt/codespace/sglang/venv/bin:/opt/bm/bin:/opt/bm/profile/s6/bin:/opt/bm/profile/s6/libexec:$PATH"

COPY platform/container/workspace/rootfs/etc/s6/skel/ /etc/s6/skel/
COPY platform/container/services/sglang/rootfs/ /
RUN chmod +x /opt/codespace/sglang/serve.sh
COPY platform/container/workspace/scripts/install-s6.sh /tmp/install-s6.sh
RUN /tmp/install-s6.sh

ENTRYPOINT ["/etc/s6/init/bin/init"]
