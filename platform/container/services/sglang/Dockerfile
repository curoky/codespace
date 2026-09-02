# Qwen3.8-Flash-Next-FP8 serving image (SGLang engine).
#
# The model architecture comes from a pinned source revision. Model weights stay
# in the bind-mounted Hugging Face cache rather than the image.
#
# sgl-deep-gemm JIT-compiles kernels at import time and needs nvcc plus CUDA
# headers. The Host driver and inference wheels provide runtime libraries only,
# so the final image also carries a slimmed CUDA Toolkit.
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

RUN apt-get update -y \
  && apt-get install -y --no-install-recommends \
    bash ca-certificates curl git zstd libgomp1 \
  && rm -rf /var/lib/apt/lists/*

ARG CUDA_HOME_DIR=/usr/local/cuda-12.9
COPY --from=cuda "${CUDA_HOME_DIR}" "${CUDA_HOME_DIR}"
ENV CUDA_HOME="${CUDA_HOME_DIR}"
ENV PATH="${CUDA_HOME_DIR}/bin:$PATH"

COPY platform/container/services/sglang/binman.yaml /tmp/binman.yaml
RUN curl -fsSL https://raw.githubusercontent.com/curoky/standalone-binaries/refs/heads/master/cmd/binman/install.sh \
    | bash -s -- --prefix /opt/bm/bin \
  && /opt/bm/bin/bm sync /tmp/binman.yaml

# Install the pinned source in a Python 3.12 venv and skip PyO3 entrypoints that
# the HTTP server does not use. Upstream dependencies default to CUDA 13, while
# the target Host uses CUDA 12: force-install the cu129 stack, remove cu13
# packages, then reinstall cu12 libraries whose shared directories were removed
# by the uninstall. torchcodec is also reinstalled so it links target nvrtc.
# Import assertions verify the normalized environment.
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
