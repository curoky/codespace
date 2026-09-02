# PyTorch built from source for 8x H100 (SM 9.0) against CUDA 13.0.
#
# 产出可直接 `import torch` 的 framework image，不包含 s6 或 serving entrypoint。
#
# CUDA 13 跨 major，runtime Host 需要 driver >=580；driver 535 只能构建，不能运行。
#
# 在匹配 toolkit 的 Ubuntu builder 中源码编译，避免 Debian final 的 glibc header
# 与 nvcc 冲突；final stage 只接收 venv 和精简后的 toolkit。

# ---- builder stage：Ubuntu 24.04 CUDA 13 devel ----
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

# 用 uv 官方 standalone 安装脚本装到 /opt/uv（不引入 binman，也无需 zstd）。
RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/opt/uv sh

ARG TORCH_REF=v2.13.0
ARG TORCHVISION_REF=v0.28.0
ARG TORCHAUDIO_REF=v2.11.0
ARG TORCH_CUDA_ARCH_LIST=9.0
ARG MAX_JOBS=4
ARG NVCC_THREADS=2
ENV FRAMEWORK_VENV=/opt/codespace/frameworks/venv
ENV UV_LINK_MODE=copy
ENV CUDA_HOME="${CUDA_HOME_DIR}"
ENV PATH="${CUDA_HOME_DIR}/bin:/opt/uv:$PATH"
RUN set -eux; \
  /opt/uv/uv venv "${FRAMEWORK_VENV}" --python 3.12; \
  FRAMEWORK_UV="/opt/uv/uv pip install --python ${FRAMEWORK_VENV}/bin/python"; \
  ${FRAMEWORK_UV} setuptools wheel ninja "cmake<4" numpy pyyaml typing_extensions; \
  export USE_CUDA=1 USE_CUDNN=1 BUILD_TEST=0 \
         TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST}" \
         MAX_JOBS="${MAX_JOBS}" NVCC_THREADS="${NVCC_THREADS}" \
         CMAKE_BUILD_PARALLEL_LEVEL="${MAX_JOBS}" \
         CMAKE_PREFIX_PATH="${FRAMEWORK_VENV}"; \
  git clone --recursive --depth 1 --branch "${TORCH_REF}" \
    https://github.com/pytorch/pytorch.git /opt/codespace/frameworks/src/pytorch; \
  ${FRAMEWORK_UV} --no-build-isolation /opt/codespace/frameworks/src/pytorch; \
  git clone --recursive --depth 1 --branch "${TORCHVISION_REF}" \
    https://github.com/pytorch/vision.git /opt/codespace/frameworks/src/vision; \
  ${FRAMEWORK_UV} --no-build-isolation /opt/codespace/frameworks/src/vision; \
  git clone --recursive --depth 1 --branch "${TORCHAUDIO_REF}" \
    https://github.com/pytorch/audio.git /opt/codespace/frameworks/src/audio; \
  ${FRAMEWORK_UV} --no-build-isolation /opt/codespace/frameworks/src/audio; \
  rm -rf /opt/codespace/frameworks/src /root/.cache/uv /root/.cache/pip /tmp/*; \
  "${FRAMEWORK_VENV}/bin/python" -c "import torch, torchvision, torchaudio; \
print(torch.__version__, torch.version.cuda); assert torch.version.cuda.startswith('13'), torch.version.cuda"

# 保守瘦身 toolkit：删静态库与编译期用不到的目录。
RUN set -eux; \
  find "${CUDA_HOME_DIR}" -name '*.a' -delete; \
  rm -rf "${CUDA_HOME_DIR}"/doc "${CUDA_HOME_DIR}"/share "${CUDA_HOME_DIR}"/src \
         "${CUDA_HOME_DIR}"/compute-sanitizer "${CUDA_HOME_DIR}"/extras \
         "${CUDA_HOME_DIR}"/compat

# ---- final stage：debian:trixie-slim ----
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
