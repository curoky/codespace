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
ENV UV_PYTHON_INSTALL_DIR=/opt/codespace/frameworks/python
ENV UV_LINK_MODE=copy
ENV CUDA_HOME="${CUDA_HOME_DIR}"
ENV PATH="${CUDA_HOME_DIR}/bin:/opt/uv:$PATH"
RUN set -eux; \
  /opt/uv/uv venv "${FRAMEWORK_VENV}" --python 3.12 --managed-python; \
  git clone --filter=blob:none --branch "${SGLANG_REF}" \
    https://github.com/sgl-project/sglang.git /opt/codespace/frameworks/src/sglang; \
  sed -i 's/cuda-python>=13\.0/cuda-python>=12,<13/' \
    /opt/codespace/frameworks/src/sglang/python/pyproject.toml; \
  sed -i 's/flashinfer_python\[cu13\]/flashinfer_python[cu12]/' \
    /opt/codespace/frameworks/src/sglang/python/pyproject.toml; \
  sed -i 's/nvidia-cutlass-dsl\[cu13\]==4\.6\.2/nvidia-cutlass-dsl==4.5.3/' \
    /opt/codespace/frameworks/src/sglang/python/pyproject.toml; \
  FRAMEWORK_UV="/opt/uv/uv pip install --python ${FRAMEWORK_VENV}/bin/python"; \
  SGLANG_BUILD_RUST_EXTS="${SGLANG_BUILD_RUST_EXTS}" \
    ${FRAMEWORK_UV} --prerelease=allow -e /opt/codespace/frameworks/src/sglang/python; \
  ${FRAMEWORK_UV} --force-reinstall ${TORCH_SPEC} \
    --index-url "https://download.pytorch.org/whl/${CUDA_TAG}"; \
  ${FRAMEWORK_UV} --force-reinstall --no-deps "sglang-kernel==0.4.6.post1" \
    --index-url "https://docs.sglang.ai/whl/${CUDA_TAG}/"; \
  ${FRAMEWORK_UV} --force-reinstall --no-deps "sgl-deep-gemm==0.1.5.post3" \
    --index-url "https://docs.sglang.ai/whl/${CUDA_TAG}/"; \
  CU13_PKGS="$(/opt/uv/uv pip list --python "${FRAMEWORK_VENV}/bin/python" \
    --format=freeze | awk -F'==' '/-cu13(==|$)/ {print $1}')"; \
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
  && apt-get install -y --no-install-recommends ca-certificates g++ libgomp1 \
  && rm -rf /var/lib/apt/lists/*

COPY --from=builder "${CUDA_HOME_DIR}" "${CUDA_HOME_DIR}"
COPY --from=builder /opt/codespace/frameworks/python /opt/codespace/frameworks/python
COPY --from=builder /opt/codespace/frameworks/venv /opt/codespace/frameworks/venv
COPY --from=builder /opt/codespace/frameworks/src/sglang /opt/codespace/frameworks/src/sglang
ENV CUDA_HOME="${CUDA_HOME_DIR}"
ENV PATH="/opt/codespace/frameworks/venv/bin:${CUDA_HOME_DIR}/bin:$PATH"

RUN python -c "import sglang, torch; assert torch.version.cuda.startswith('12')" \
  && printf '%s\n' '#include <cuda_runtime.h>' '__global__ void kernel() {}' \
    >/tmp/cuda-smoke.cu \
  && nvcc -std=c++20 -arch=sm_90a -c /tmp/cuda-smoke.cu -o /tmp/cuda-smoke.o \
  && rm /tmp/cuda-smoke.cu /tmp/cuda-smoke.o

ENTRYPOINT ["/opt/codespace/frameworks/venv/bin/python"]
