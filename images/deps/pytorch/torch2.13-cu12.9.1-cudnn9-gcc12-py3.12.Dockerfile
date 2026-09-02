# PyTorch built from source for 8x H100 (SM 9.0) against CUDA 12.9.
#
# 与 images/deps/AGENTS.md 公共契约一致：从源码编译的开发依赖镜像，产出可直接
# `import torch` 的可运行镜像（无 s6、无 serving entrypoint），与 images/deployments/ 的
# serving 镜像刻意区分。
#
# 版本组合（即文件名声明）：torch v2.13.0 + torchvision v0.28.0 + torchaudio v2.11.0
# 驱动，经 CUDA 12 minor version 前向兼容可运行 cu12.9 编译产物。
#
# 关键装配决策——为何在 cuda(Ubuntu 24.04) stage 内编译而非 debian final：
# nvidia/cuda 的 nvcc 头文件（crt/math_functions.h 的 cospi/sinpi noexcept 声明）
# 与 debian:trixie 过新的 glibc（bits/mathcalls.h）冲突，编译期直接
# `error: exception specification is incompatible`。故在与 toolkit 匹配的 Ubuntu
# 24.04 devel stage 内完成源码编译，产出独立 venv，再把 venv + 瘦身后的 toolkit
# COPY 进 debian:trixie-slim final（满足 final 用 debian 的约定，又避开 glibc 冲突）。

# ---- builder stage：Ubuntu 24.04 CUDA devel，glibc 与 nvcc 匹配，在此源码编译 ----
ARG CUDA_DEVEL_IMAGE=docker.io/nvidia/cuda:12.9.1-cudnn-devel-ubuntu24.04
ARG CUDA_HOME_DIR=/usr/local/cuda-12.9
FROM ${CUDA_DEVEL_IMAGE} AS builder
ARG CUDA_HOME_DIR

# 编译期系统依赖：gcc-12/g++-12（cu12.9 nvcc host compiler；PyTorch C++20 头文件要求
# gcc>=11.3，nvcc 上限 gcc<=13，取 gcc12）、git、curl/ca-certificates（binman + TLS）、
# zstd（binman 解包）。Ubuntu 24.04 默认 gcc-13，显式装 gcc-12 并设为默认。
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends \
    ca-certificates curl git zstd gcc-12 g++-12 \
  && update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-12 60 \
       --slave /usr/bin/g++ g++ /usr/bin/g++-12 \
  && rm -rf /var/lib/apt/lists/*

COPY images/deps/pytorch/binman.yaml /tmp/binman.yaml
RUN curl -fsSL https://raw.githubusercontent.com/curoky/standalone-binaries/refs/heads/master/cmd/binman/install.sh \
    | bash -s -- --prefix /opt/bm/bin \
  && /opt/bm/bin/bm sync /tmp/binman.yaml

# 源码编译 PyTorch 三件套并装入独立 venv。
#
# 版本 pin：torch v2.13.0，torchvision v0.28.0，torchaudio v2.11.0（torchaudio 版本
# 线独立于 torch，2.11.0 是与 torch 2.13.0 配对的版本），见 images/deps/AGENTS.md。
#
# TORCH_CUDA_ARCH_LIST="9.0"：只为本机 H100（Hopper，SM 9.0）编译，显著缩短构建
# 时间、减小体积。如需 JIT 前向兼容更高驱动可改 "9.0+PTX"。
#
# 编译资源约束（重要）：本机内存紧张（~3 GiB），CUDA kernel 源码编译单进程吃数 GB，
# 绝不能按 nproc（192）并行否则 OOM。MAX_JOBS 保守默认 4、NVCC_THREADS 默认 2；
# 内存告急时进一步调小，不要放开。
#
# 现代构建流程用 `uv pip install --no-build-isolation`（setup.py install 已废弃），
# 复用 venv 内预装的 torch（vision/audio 编译期依赖 torch）。
ARG TORCH_REF=v2.13.0
ARG TORCHVISION_REF=v0.28.0
ARG TORCHAUDIO_REF=v2.11.0
ARG TORCH_CUDA_ARCH_LIST=9.0
ARG MAX_JOBS=4
ARG NVCC_THREADS=2
ENV DEPS_VENV=/opt/deps/venv
ENV UV_LINK_MODE=copy
ENV CUDA_HOME="${CUDA_HOME_DIR}"
ENV PATH="${CUDA_HOME_DIR}/bin:/opt/bm/bin:$PATH"
RUN set -eux; \
  /opt/bm/bin/uv venv "${DEPS_VENV}" --python 3.12; \
  DEPS_UV="/opt/bm/bin/uv pip install --python ${DEPS_VENV}/bin/python"; \
  ${DEPS_UV} setuptools wheel ninja "cmake<4" numpy pyyaml typing_extensions; \
  export USE_CUDA=1 USE_CUDNN=1 BUILD_TEST=0 \
         TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST}" \
         MAX_JOBS="${MAX_JOBS}" NVCC_THREADS="${NVCC_THREADS}" \
         CMAKE_BUILD_PARALLEL_LEVEL="${MAX_JOBS}" \
         CMAKE_PREFIX_PATH="${DEPS_VENV}"; \
  git clone --recursive --depth 1 --branch "${TORCH_REF}" \
    https://github.com/pytorch/pytorch.git /opt/deps/src/pytorch; \
  ${DEPS_UV} --no-build-isolation /opt/deps/src/pytorch; \
  git clone --recursive --depth 1 --branch "${TORCHVISION_REF}" \
    https://github.com/pytorch/vision.git /opt/deps/src/vision; \
  ${DEPS_UV} --no-build-isolation /opt/deps/src/vision; \
  git clone --recursive --depth 1 --branch "${TORCHAUDIO_REF}" \
    https://github.com/pytorch/audio.git /opt/deps/src/audio; \
  ${DEPS_UV} --no-build-isolation /opt/deps/src/audio; \
  rm -rf /opt/deps/src /root/.cache/uv /root/.cache/pip /tmp/*; \
  "${DEPS_VENV}/bin/python" -c "import torch, torchvision, torchaudio; \
print(torch.__version__, torch.version.cuda); assert torch.version.cuda.startswith('12'), torch.version.cuda"

# 瘦身 toolkit（保守起步）：删静态库 *.a 与编译期用不到的 doc/share/src/extras/
# compute-sanitizer/compat，供下面 COPY 进 final 时体积更小。
RUN set -eux; \
  find "${CUDA_HOME_DIR}" -name '*.a' -delete; \
  rm -rf "${CUDA_HOME_DIR}"/doc "${CUDA_HOME_DIR}"/share "${CUDA_HOME_DIR}"/src \
         "${CUDA_HOME_DIR}"/compute-sanitizer "${CUDA_HOME_DIR}"/extras \
         "${CUDA_HOME_DIR}"/compat

# ---- final stage：debian:trixie-slim，仅装运行期依赖，COPY 编译产物 ----
FROM docker.io/debian:trixie-slim
ARG CUDA_HOME_DIR

# 运行期依赖：libgomp1（torch OpenMP 运行时）、ca-certificates。venv 自带 CPython，
# CUDA runtime 由编译产物 + 拷入的 toolkit 提供，无需系统 python/gcc。
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates libgomp1 \
  && rm -rf /var/lib/apt/lists/*

COPY --from=builder "${CUDA_HOME_DIR}" "${CUDA_HOME_DIR}"
COPY --from=builder /opt/deps/venv /opt/deps/venv
ENV CUDA_HOME="${CUDA_HOME_DIR}"
ENV PATH="/opt/deps/venv/bin:${CUDA_HOME_DIR}/bin:$PATH"

# 可运行镜像：缺省进 venv 的 python。运行需 host NVIDIA Container Toolkit 注入
# driver（--device nvidia.com/gpu=all）；容器内 `import torch` 即可用 GPU。
ENTRYPOINT ["/opt/deps/venv/bin/python"]
