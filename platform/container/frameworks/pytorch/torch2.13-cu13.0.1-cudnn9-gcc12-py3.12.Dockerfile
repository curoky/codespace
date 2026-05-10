# PyTorch built from source for 8x H100 (SM 9.0) against CUDA 13.0.
#
# 与 platform/container/frameworks/AGENTS.md 公共契约一致：从源码编译的开发依赖镜像，产出可直接
# `import torch` 的可运行镜像（无 s6、无 serving entrypoint）。
#
# 版本组合（即文件名声明）：torch v2.13.0 + torchvision v0.28.0 + torchaudio v2.11.0
#
# 注意：CUDA 13 跨 major，运行需 host driver >=580；本机 driver 535 可编译此镜像但
# 无法运行（仅本机可运行版本见同目录 cu12.9.1 文件）。本文件用于面向 >=580 驱动
# 主机的产物构建与在本机的编译验证。
#
# 装配决策：与 cu12.9 版本一致，在 cuda(Ubuntu 24.04) devel stage 内源码编译
# （glibc 与 nvcc 匹配，避开 debian:trixie 头文件冲突），venv 再 COPY 进
# debian:trixie-slim final。差异仅 CUDA base image / CUDA_HOME_DIR / torch 索引。

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
