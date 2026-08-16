# --------------------------------- Builder ----------------------------------
# CUDA 13 跨 major，runtime Host 需要 driver >=580；driver 535 只能构建，不能运行。
ARG CUDA_DEVEL_IMAGE=docker.io/nvidia/cuda:13.0.1-cudnn-devel-ubuntu24.04
ARG CUDA_HOME_DIR=/usr/local/cuda-13.0
FROM ${CUDA_DEVEL_IMAGE} AS builder
ARG CUDA_HOME_DIR

RUN apt-get update -y \
  && apt-get install -y --no-install-recommends \
    ca-certificates curl git gcc-12 g++-12 \
  && update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-12 60 \
       --slave /usr/bin/g++ g++ /usr/bin/g++-12 \
  && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/opt/uv sh

# Build parallelism is capped for the memory-constrained builder.
ARG VLLM_REF=v0.28.0
ARG CUDA_TAG=cu130
ARG TORCH_SPEC="torch==2.13.0 torchvision==0.28.0 torchaudio==2.11.0"
ARG TORCH_CUDA_ARCH_LIST=9.0a
ARG MAX_JOBS=4
ARG NVCC_THREADS=2
ENV FRAMEWORK_VENV=/opt/codespace/frameworks/venv
ENV UV_LINK_MODE=copy
ENV CUDA_HOME="${CUDA_HOME_DIR}"
ENV PATH="${CUDA_HOME_DIR}/bin:/opt/uv:$PATH"
RUN set -eux; \
  /opt/uv/uv venv "${FRAMEWORK_VENV}" --python 3.12; \
  FRAMEWORK_UV="/opt/uv/uv pip install --python ${FRAMEWORK_VENV}/bin/python"; \
  ${FRAMEWORK_UV} ${TORCH_SPEC} \
    --index-url "https://download.pytorch.org/whl/${CUDA_TAG}"; \
  ${FRAMEWORK_UV} setuptools wheel "setuptools-scm>=8" setuptools_rust "cmake<4" ninja packaging; \
  git clone --filter=blob:none --branch "${VLLM_REF}" \
    https://github.com/vllm-project/vllm.git /opt/codespace/frameworks/src/vllm; \
  export VLLM_TARGET_DEVICE=cuda \
         TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST}" \
         MAX_JOBS="${MAX_JOBS}" NVCC_THREADS="${NVCC_THREADS}" \
         CMAKE_BUILD_PARALLEL_LEVEL="${MAX_JOBS}"; \
  ${FRAMEWORK_UV} --no-build-isolation -e /opt/codespace/frameworks/src/vllm; \
  rm -rf /root/.cache/uv /root/.cache/pip /tmp/*; \
  "${FRAMEWORK_VENV}/bin/python" -c "import torch, vllm; \
print(vllm.__version__, torch.version.cuda); assert torch.version.cuda.startswith('13'), torch.version.cuda"

RUN set -eux; \
  find "${CUDA_HOME_DIR}" -name '*.a' -delete; \
  rm -rf "${CUDA_HOME_DIR}"/doc "${CUDA_HOME_DIR}"/share "${CUDA_HOME_DIR}"/src \
         "${CUDA_HOME_DIR}"/compute-sanitizer "${CUDA_HOME_DIR}"/extras \
         "${CUDA_HOME_DIR}"/compat

# --------------------------------- Runtime ----------------------------------
# Editable installation requires the source tree in the final image.
FROM docker.io/debian:trixie-slim
ARG CUDA_HOME_DIR

RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates libgomp1 \
  && rm -rf /var/lib/apt/lists/*

COPY --from=builder "${CUDA_HOME_DIR}" "${CUDA_HOME_DIR}"
COPY --from=builder /opt/codespace/frameworks/venv /opt/codespace/frameworks/venv
COPY --from=builder /opt/codespace/frameworks/src/vllm /opt/codespace/frameworks/src/vllm
ENV CUDA_HOME="${CUDA_HOME_DIR}"
ENV PATH="/opt/codespace/frameworks/venv/bin:${CUDA_HOME_DIR}/bin:$PATH"

ENTRYPOINT ["/opt/codespace/frameworks/venv/bin/python"]
