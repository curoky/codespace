# --------------------------------- Builder ----------------------------------
# The HTTP runtime does not need SGLang's PyO3 entrypoints.
ARG CUDA_DEVEL_IMAGE=docker.io/nvidia/cuda:12.9.1-cudnn-devel-ubuntu24.04
ARG CUDA_HOME_DIR=/usr/local/cuda-12.9
FROM ${CUDA_DEVEL_IMAGE} AS builder
ARG CUDA_HOME_DIR

RUN apt-get update -y \
  && apt-get install -y --no-install-recommends \
    ca-certificates curl git gcc-12 g++-12 \
  && update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-12 60 \
       --slave /usr/bin/g++ g++ /usr/bin/g++-12 \
  && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/opt/uv sh

# Upstream defaults to CUDA 13; normalize the complete stack back to CUDA 12.9.
ARG SGLANG_REF=v0.5.18
ARG CUDA_TAG=cu129
ARG TORCH_SPEC="torch==2.13.0 torchvision==0.28.0 torchaudio==2.11.0"
ARG SGLANG_BUILD_RUST_EXTS=none
ENV FRAMEWORK_VENV=/opt/codespace/frameworks/venv
ENV UV_LINK_MODE=copy
ENV CUDA_HOME="${CUDA_HOME_DIR}"
ENV PATH="${CUDA_HOME_DIR}/bin:/opt/uv:$PATH"
RUN set -eux; \
  /opt/uv/uv venv "${FRAMEWORK_VENV}" --python 3.12; \
  git clone --filter=blob:none --branch "${SGLANG_REF}" \
    https://github.com/sgl-project/sglang.git /opt/codespace/frameworks/src/sglang; \
  FRAMEWORK_UV="/opt/uv/uv pip install --python ${FRAMEWORK_VENV}/bin/python"; \
  SGLANG_BUILD_RUST_EXTS="${SGLANG_BUILD_RUST_EXTS}" \
    ${FRAMEWORK_UV} --prerelease=allow -e /opt/codespace/frameworks/src/sglang/python; \
  ${FRAMEWORK_UV} --force-reinstall ${TORCH_SPEC} \
    --index-url "https://download.pytorch.org/whl/${CUDA_TAG}"; \
  ${FRAMEWORK_UV} --force-reinstall sglang-kernel \
    --index-url "https://docs.sglang.ai/whl/${CUDA_TAG}/"; \
  ${FRAMEWORK_UV} --force-reinstall sgl-deep-gemm --no-deps \
    --index-url "https://docs.sglang.ai/whl/${CUDA_TAG}/"; \
  CU13_PKGS="$(ls -d ${FRAMEWORK_VENV}/lib/python3.12/site-packages/*.dist-info \
    | sed 's#.*/##;s/.dist-info//' \
    | awk -F- '/^nvidia/ {name=$1; ver=$2; if (ver ~ /^13\./ || name ~ /_cu13$/) print name}' \
    | grep -vE 'nvidia_ml_py')"; \
  for p in ${CU13_PKGS}; do /opt/uv/uv pip uninstall --python ${FRAMEWORK_VENV}/bin/python "$p"; done; \
  rm -rf ${FRAMEWORK_VENV}/lib/python3.12/site-packages/nvidia/cu13; \
  ${FRAMEWORK_UV} --reinstall --index-url "https://download.pytorch.org/whl/${CUDA_TAG}" \
    nvidia-cudnn-cu12 nvidia-cusparselt-cu12 nvidia-nccl-cu12 nvidia-nvshmem-cu12; \
  rm -rf /opt/codespace/frameworks/src/sglang/.git /root/.cache/uv /root/.cache/pip /tmp/*; \
  "${FRAMEWORK_VENV}/bin/python" -c "import torch; assert torch.version.cuda.startswith('12'), torch.version.cuda"

# sgl-deep-gemm requires nvcc and headers at runtime.
RUN set -eux; \
  find "${CUDA_HOME_DIR}" -name '*.a' -delete; \
  rm -rf "${CUDA_HOME_DIR}"/doc "${CUDA_HOME_DIR}"/share "${CUDA_HOME_DIR}"/src \
         "${CUDA_HOME_DIR}"/compute-sanitizer "${CUDA_HOME_DIR}"/extras \
         "${CUDA_HOME_DIR}"/compat

# --------------------------------- Runtime ----------------------------------
FROM docker.io/debian:trixie-slim
ARG CUDA_HOME_DIR

RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates libgomp1 \
  && rm -rf /var/lib/apt/lists/*

COPY --from=builder "${CUDA_HOME_DIR}" "${CUDA_HOME_DIR}"
COPY --from=builder /opt/codespace/frameworks/venv /opt/codespace/frameworks/venv
ENV CUDA_HOME="${CUDA_HOME_DIR}"
ENV PATH="/opt/codespace/frameworks/venv/bin:${CUDA_HOME_DIR}/bin:$PATH"

ENTRYPOINT ["/opt/codespace/frameworks/venv/bin/python"]
