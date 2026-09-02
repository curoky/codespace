# SGLang built from source for 8x H100 (SM 9.0) against CUDA 13.0.
#
# 与 images/deps/AGENTS.md 公共契约一致：从源码编译的开发依赖镜像，产出可
# `import sglang` 的可运行镜像（无 s6、无 serving entrypoint）。
#
# 版本组合（即文件名声明）：sglang v0.5.18，CUDA 13.0.1，gcc-12，Python 3.12，
# 依赖 torch==2.13.0。CUDA 13 正是 sglang v0.5.18 的默认目标（cu130），依赖直接走
# cu13 索引，无需 cu12.9 版本里的 cu13 清理逻辑。
#
# 注意：CUDA 13 运行需 host driver >=580；本机 driver 535 可编译但无法运行（本机
# 可运行版本见同目录 cu12.9.1 文件）。
#
# 装配决策：在 cuda(Ubuntu 24.04) devel stage 内安装（glibc 与 toolkit 匹配），
# venv 再 COPY 进 debian:trixie-slim final。

# ---- builder stage：Ubuntu 24.04 CUDA 13 devel ----
ARG CUDA_DEVEL_IMAGE=docker.io/nvidia/cuda:13.0.1-cudnn-devel-ubuntu24.04
ARG CUDA_HOME_DIR=/usr/local/cuda-13.0
FROM ${CUDA_DEVEL_IMAGE} AS builder
ARG CUDA_HOME_DIR

RUN apt-get update -y \
  && apt-get install -y --no-install-recommends \
    ca-certificates curl git zstd gcc-12 g++-12 \
  && update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-12 60 \
       --slave /usr/bin/g++ g++ /usr/bin/g++-12 \
  && rm -rf /var/lib/apt/lists/*

COPY images/deps/sglang/binman.yaml /tmp/binman.yaml
RUN curl -fsSL https://raw.githubusercontent.com/curoky/standalone-binaries/refs/heads/master/cmd/binman/install.sh \
    | bash -s -- --prefix /opt/bm/bin \
  && /opt/bm/bin/bm sync /tmp/binman.yaml

# 源码构建 sglang 主包并装入独立 venv，随后按 cu130 索引强制重装 torch 三件套与 GPU
# kernel（cu13 是 sglang v0.5.18 默认目标，依赖天然拉 cu13，无需清理）。
ARG SGLANG_REF=v0.5.18
ARG CUDA_TAG=cu130
ARG TORCH_SPEC="torch==2.13.0 torchvision==0.28.0 torchaudio==2.11.0"
ARG SGLANG_BUILD_RUST_EXTS=none
ENV DEPS_VENV=/opt/deps/venv
ENV UV_LINK_MODE=copy
ENV CUDA_HOME="${CUDA_HOME_DIR}"
ENV PATH="${CUDA_HOME_DIR}/bin:/opt/bm/bin:$PATH"
RUN set -eux; \
  /opt/bm/bin/uv venv "${DEPS_VENV}" --python 3.12; \
  git clone --filter=blob:none --branch "${SGLANG_REF}" \
    https://github.com/sgl-project/sglang.git /opt/deps/src/sglang; \
  DEPS_UV="/opt/bm/bin/uv pip install --python ${DEPS_VENV}/bin/python"; \
  SGLANG_BUILD_RUST_EXTS="${SGLANG_BUILD_RUST_EXTS}" \
    ${DEPS_UV} --prerelease=allow -e /opt/deps/src/sglang/python; \
  ${DEPS_UV} --force-reinstall ${TORCH_SPEC} \
    --index-url "https://download.pytorch.org/whl/${CUDA_TAG}"; \
  ${DEPS_UV} --force-reinstall sglang-kernel \
    --index-url "https://docs.sglang.ai/whl/${CUDA_TAG}/"; \
  ${DEPS_UV} --force-reinstall sgl-deep-gemm --no-deps \
    --index-url "https://docs.sglang.ai/whl/${CUDA_TAG}/"; \
  rm -rf /opt/deps/src/sglang/.git /root/.cache/uv /root/.cache/pip /tmp/*; \
  "${DEPS_VENV}/bin/python" -c "import torch; assert torch.version.cuda.startswith('13'), torch.version.cuda"

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
COPY --from=builder /opt/deps/venv /opt/deps/venv
ENV CUDA_HOME="${CUDA_HOME_DIR}"
ENV PATH="/opt/deps/venv/bin:${CUDA_HOME_DIR}/bin:$PATH"

ENTRYPOINT ["/opt/deps/venv/bin/python"]
