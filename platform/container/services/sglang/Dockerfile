# ---------------------------- CUDA toolchain --------------------------------
# sgl-deep-gemm JIT requires nvcc and CUDA headers in the runtime image.
ARG CUDA_DEVEL_IMAGE=docker.io/nvidia/cuda:12.9.1-devel-ubuntu24.04
FROM ${CUDA_DEVEL_IMAGE} AS cuda
ARG CUDA_HOME_DIR=/usr/local/cuda-12.9
RUN set -eux; \
  find "${CUDA_HOME_DIR}" -name '*.a' -delete; \
  rm -rf "${CUDA_HOME_DIR}"/targets/*/lib/libnpp* \
         "${CUDA_HOME_DIR}"/doc "${CUDA_HOME_DIR}"/share "${CUDA_HOME_DIR}"/src \
         "${CUDA_HOME_DIR}"/compute-sanitizer "${CUDA_HOME_DIR}"/extras \
         "${CUDA_HOME_DIR}"/compat

# -------------------------------- s6 assets ---------------------------------
ARG S6_BASE_IMAGE=ghcr.io/curoky/codespace:service-s6
FROM ${S6_BASE_IMAGE} AS s6

# --------------------------------- Runtime ----------------------------------
FROM docker.io/ubuntu:24.04

COPY --from=s6 /opt/bm /opt/bm

RUN apt-get update -y \
  && apt-get install -y --no-install-recommends \
    bash ca-certificates g++ git libgomp1 \
  && command -v cc \
  && command -v c++ \
  && rm -rf /var/lib/apt/lists/*

ARG CUDA_HOME_DIR=/usr/local/cuda-12.9
COPY --from=cuda "${CUDA_HOME_DIR}" "${CUDA_HOME_DIR}"
ENV CUDA_HOME="${CUDA_HOME_DIR}"
ENV PATH="${CUDA_HOME_DIR}/bin:$PATH"
RUN printf '%s\n' '#include <cuda_runtime.h>' '__global__ void kernel() {}' \
      >/tmp/cuda-smoke.cu \
  && nvcc -std=c++20 -arch=sm_90a -c /tmp/cuda-smoke.cu -o /tmp/cuda-smoke.o \
  && rm /tmp/cuda-smoke.cu /tmp/cuda-smoke.o

RUN /opt/bm/bin/bm install uv

# Upstream defaults to CUDA 13; normalize the complete stack back to CUDA 12.9.
ARG SGLANG_REF=pull/36497/head
ARG CUDA_TAG=cu129
ARG TORCH_SPEC="torch==2.13.0 torchvision==0.28.0 torchaudio==2.11.0"
# This flash-attn beta selects a removed CUTLASS signature on CUDA 12.9.
ARG FLASH_ATTN_SPEC="flash-attn-4==4.0.0b19"
ARG SGLANG_BUILD_RUST_EXTS=none
ENV UV_LINK_MODE=copy
RUN /opt/bm/bin/uv venv /opt/sglang/venv --python 3.12 \
  && git clone --filter=blob:none https://github.com/sgl-project/sglang.git /opt/sglang/src \
  && git -C /opt/sglang/src fetch origin "${SGLANG_REF}" \
  && git -C /opt/sglang/src checkout FETCH_HEAD \
  && SERVE_UV="/opt/bm/bin/uv pip install --python /opt/sglang/venv/bin/python" \
  && SGLANG_BUILD_RUST_EXTS="${SGLANG_BUILD_RUST_EXTS}" \
       ${SERVE_UV} --prerelease=allow -e /opt/sglang/src/python \
  && ${SERVE_UV} --no-deps ${FLASH_ATTN_SPEC} \
  && FA4_UTILS="/opt/sglang/venv/lib/python3.12/site-packages/flash_attn/cute/utils.py" \
  && grep -Fq 'if CUDA_VERSION.major == 12 and CUDA_VERSION.minor == 9:' "${FA4_UTILS}" \
  && sed -i 's/if CUDA_VERSION.major == 12 and CUDA_VERSION.minor == 9:/if False:/' "${FA4_UTILS}" \
  && ${SERVE_UV} --force-reinstall ${TORCH_SPEC} \
       --index-url "https://download.pytorch.org/whl/${CUDA_TAG}" \
  && ${SERVE_UV} --force-reinstall sglang-kernel \
       --index-url "https://docs.sglang.ai/whl/${CUDA_TAG}/" \
  && ${SERVE_UV} --force-reinstall sgl-deep-gemm --no-deps \
       --index-url "https://docs.sglang.ai/whl/${CUDA_TAG}/" \
  && CU13_PKGS="$(ls -d /opt/sglang/venv/lib/python3.12/site-packages/*.dist-info \
       | sed 's#.*/##;s/.dist-info//' \
       | awk -F- '/^nvidia/ {name=$1; ver=$2; if (ver ~ /^13\./ || name ~ /_cu13$/) print name}' \
       | grep -vE 'nvidia_ml_py')" \
  && for p in ${CU13_PKGS}; do /opt/bm/bin/uv pip uninstall --python /opt/sglang/venv/bin/python "$p"; done \
  && rm -rf /opt/sglang/venv/lib/python3.12/site-packages/nvidia/cu13 \
  && ${SERVE_UV} --reinstall --index-url "https://download.pytorch.org/whl/${CUDA_TAG}" \
       nvidia-cudnn-cu12 nvidia-cusparselt-cu12 nvidia-nccl-cu12 nvidia-nvshmem-cu12 \
       torchcodec \
  && rm -rf /opt/sglang/src/.git \
  && /opt/sglang/venv/bin/python -c "import torch; assert torch.version.cuda.startswith('12'), torch.version.cuda" \
  && /opt/sglang/venv/bin/python -c "import torchcodec.decoders" \
  && rm -rf /root/.cache/uv

ENV PATH="/opt/sglang/venv/bin:/opt/bm/bin:/opt/bm/profile/s6/bin:/opt/bm/profile/s6/libexec:$PATH"

COPY --from=s6 /etc/s6/skel/ /etc/s6/skel/
COPY platform/container/services/sglang/rootfs/ /
COPY --from=s6 /etc/s6/install-s6.sh /tmp/install-s6.sh
RUN /tmp/install-s6.sh

ENTRYPOINT ["/etc/s6/init/bin/init"]
