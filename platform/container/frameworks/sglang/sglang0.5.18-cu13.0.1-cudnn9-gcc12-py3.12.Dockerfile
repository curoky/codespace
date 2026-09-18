# --------------------------------- Builder ----------------------------------
# CUDA 13 runtime Host 需要 driver >=580；driver 535 只能构建，不能运行。
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

ARG SGLANG_REF=v0.5.18
ARG CUDA_TAG=cu130
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
  rm -rf /opt/codespace/frameworks/src/sglang/.git /root/.cache/uv /root/.cache/pip /tmp/*; \
  "${FRAMEWORK_VENV}/bin/python" -c "import torch; assert torch.version.cuda.startswith('13'), torch.version.cuda"

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
