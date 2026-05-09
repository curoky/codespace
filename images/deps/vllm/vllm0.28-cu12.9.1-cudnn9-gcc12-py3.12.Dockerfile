# vLLM built from source for 8x H100 (SM 9.0) against CUDA 12.9.
#
# 与 images/deps/AGENTS.md 公共契约一致：从源码编译的开发依赖镜像，产出可
# `import vllm` 的可运行镜像（无 s6、无 serving entrypoint）。与 images/deployments/ 的
# serving 镜像刻意区分。
#
# 版本组合（即文件名声明）：vllm v0.28.0，CUDA 12.9.1，gcc-12，Python 3.12，
# 依赖 torch==2.13.0（v0.28.0 的 requirements/cuda.txt 所 pin）。本机 driver 535
# 经 CUDA 12 minor 前向兼容跑 cu12.9。
#
# 装配决策：在 cuda(Ubuntu 24.04) devel stage 内从源码编译 vLLM 的 CUDA/C++ 内核
# （glibc 与 nvcc 匹配，避开 debian:trixie 的头文件冲突），产出 venv 再 COPY 进
# debian:trixie-slim final。vLLM 编译期依赖已安装的 torch（cmake 读 torch 的 CUDA
# 配置），故先装 cu129 对齐的 torch 三件套，再 `-e . --no-build-isolation` 编译。

# ---- builder stage：Ubuntu 24.04 CUDA devel ----
ARG CUDA_DEVEL_IMAGE=docker.io/nvidia/cuda:12.9.1-cudnn-devel-ubuntu24.04
ARG CUDA_HOME_DIR=/usr/local/cuda-12.9
FROM ${CUDA_DEVEL_IMAGE} AS builder
ARG CUDA_HOME_DIR

# 编译期系统依赖：gcc-12/g++-12（cu12.9 host compiler，vLLM 要求 gcc>=11.3）、
# cmake 由 uv 装的 build 依赖提供，git/curl/ca-certificates/zstd 供 clone 与 binman。
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends \
    ca-certificates curl git zstd gcc-12 g++-12 \
  && update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-12 60 \
       --slave /usr/bin/g++ g++ /usr/bin/g++-12 \
  && rm -rf /var/lib/apt/lists/*

COPY images/deps/vllm/binman.yaml /tmp/binman.yaml
RUN curl -fsSL https://raw.githubusercontent.com/curoky/standalone-binaries/refs/heads/master/cmd/binman/install.sh \
    | bash -s -- --prefix /opt/bm/bin \
  && /opt/bm/bin/bm sync /tmp/binman.yaml

# 先装 cu129 对齐的 torch 三件套（vLLM 编译期必须先有 torch），再从源码编译 vLLM
# 的 CUDA/C++ 内核并装入独立 venv。
#
# VLLM_TARGET_DEVICE=cuda + TORCH_CUDA_ARCH_LIST="9.0a"：只为本机 H100（Hopper，
# SM 9.0）编译；用 9.0a 变体启用 Hopper 专属指令（wgmma/TMA），vLLM 的 Fp8 与
# cutlass kernel 依赖之。--no-build-isolation 复用已装 torch，否则 cmake 找不到
# torch 配置。
#
# 编译资源约束（重要）：本机内存紧张（~3 GiB），MAX_JOBS 保守默认 4、NVCC_THREADS
# 默认 2，绝不按 nproc（192）并行否则 OOM；内存告急时进一步调小。
ARG VLLM_REF=v0.28.0
ARG CUDA_TAG=cu129
ARG TORCH_SPEC="torch==2.13.0 torchvision==0.28.0 torchaudio==2.11.0"
ARG TORCH_CUDA_ARCH_LIST=9.0a
ARG MAX_JOBS=4
ARG NVCC_THREADS=2
ENV DEPS_VENV=/opt/deps/venv
ENV UV_LINK_MODE=copy
ENV CUDA_HOME="${CUDA_HOME_DIR}"
ENV PATH="${CUDA_HOME_DIR}/bin:/opt/bm/bin:$PATH"
RUN set -eux; \
  /opt/bm/bin/uv venv "${DEPS_VENV}" --python 3.12; \
  DEPS_UV="/opt/bm/bin/uv pip install --python ${DEPS_VENV}/bin/python"; \
  ${DEPS_UV} ${TORCH_SPEC} \
    --index-url "https://download.pytorch.org/whl/${CUDA_TAG}"; \
  ${DEPS_UV} setuptools wheel "setuptools-scm>=8" setuptools_rust "cmake<4" ninja packaging; \
  git clone --filter=blob:none --branch "${VLLM_REF}" \
    https://github.com/vllm-project/vllm.git /opt/deps/src/vllm; \
  export VLLM_TARGET_DEVICE=cuda \
         TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST}" \
         MAX_JOBS="${MAX_JOBS}" NVCC_THREADS="${NVCC_THREADS}" \
         CMAKE_BUILD_PARALLEL_LEVEL="${MAX_JOBS}"; \
  ${DEPS_UV} --no-build-isolation -e /opt/deps/src/vllm; \
  rm -rf /root/.cache/uv /root/.cache/pip /tmp/*; \
  "${DEPS_VENV}/bin/python" -c "import torch, vllm; \
print(vllm.__version__, torch.version.cuda); assert torch.version.cuda.startswith('12'), torch.version.cuda"

# 保守瘦身 toolkit：删静态库与编译期用不到的目录。
RUN set -eux; \
  find "${CUDA_HOME_DIR}" -name '*.a' -delete; \
  rm -rf "${CUDA_HOME_DIR}"/doc "${CUDA_HOME_DIR}"/share "${CUDA_HOME_DIR}"/src \
         "${CUDA_HOME_DIR}"/compute-sanitizer "${CUDA_HOME_DIR}"/extras \
         "${CUDA_HOME_DIR}"/compat

# ---- final stage：debian:trixie-slim ----
# vllm 以 editable 装入 venv，源码树 /opt/deps/src/vllm 需保留（venv 内有 .pth 指向
# 它），故一并 COPY。
FROM docker.io/debian:trixie-slim
ARG CUDA_HOME_DIR

RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates libgomp1 \
  && rm -rf /var/lib/apt/lists/*

COPY --from=builder "${CUDA_HOME_DIR}" "${CUDA_HOME_DIR}"
COPY --from=builder /opt/deps/venv /opt/deps/venv
COPY --from=builder /opt/deps/src/vllm /opt/deps/src/vllm
ENV CUDA_HOME="${CUDA_HOME_DIR}"
ENV PATH="/opt/deps/venv/bin:${CUDA_HOME_DIR}/bin:$PATH"

# 可运行镜像：缺省进 venv 的 python；也可
# `python -m vllm.entrypoints.openai.api_server ...` 起 serving。运行需 host NVIDIA
# Container Toolkit 注入 driver。
ENTRYPOINT ["/opt/deps/venv/bin/python"]
