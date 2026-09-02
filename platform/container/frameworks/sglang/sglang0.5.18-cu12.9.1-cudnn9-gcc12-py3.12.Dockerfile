# SGLang built from source for 8x H100 (SM 9.0) against CUDA 12.9.
#
# 与 platform/container/frameworks/AGENTS.md 公共契约一致：从源码编译的开发依赖镜像，产出可
# `import sglang` 的可运行镜像（无 s6、无 serving entrypoint）。与 platform/container/services/ 的
# serving 镜像刻意区分。
#
# 版本组合（即文件名声明）：sglang v0.5.18，CUDA 12.9.1，gcc-12，Python 3.12，
# 依赖 torch==2.13.0（v0.5.18 的 pyproject 所 pin）。本机 driver 535 经 CUDA 12
# minor 前向兼容跑 cu12.9。
#
# 装配决策：与 pytorch Dockerfile 一致，在 cuda(Ubuntu 24.04) devel stage 内完成
# 安装（glibc 与 toolkit 匹配，避开 debian:trixie 的 nvcc/glibc 头文件冲突），
# 产出 venv 再 COPY 进 debian:trixie-slim final。
#
# 从源码编译 vs 装 wheel：clone v0.5.18 tag 后从 python/ 源码 editable 安装 sglang
# 主包；GPU kernel（sglang-kernel / sgl-deep-gemm）与 torch 三件套从 cu129 官方索引
# 装预编译 wheel——整栈源码编译 CUDA kernel 成本极高，主包源码编译已满足目标。
#
# SGLANG_BUILD_RUST_EXTS=none：跳过 PyO3 Rust 扩展（需 cargo，仅支撑 gRPC/多模态
# 入口），OpenAI HTTP server 不需要。

# ---- builder stage：Ubuntu 24.04 CUDA devel ----
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

# 用 uv 官方 standalone 安装脚本装到 /opt/uv（不引入 binman，也无需 zstd）。
RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/opt/uv sh

# 源码构建 sglang 主包并装入独立 venv，随后按官方 cu129 recipe 强制重装 cu129 对齐
# 的 torch 三件套与 GPU kernel，最后清理 cu13 冗余 wheel（sglang 依赖默认拉 cu13，
# 一台 driver-535/CUDA-12 主机永远加载不了 cu13，需 driver>=580）。cu13 清理逻辑与
# platform/container/services/sglang/Dockerfile 保持一致：卸载 13.x/_cu13 的 nvidia 包（保留
# nvidia_ml_py），删独占的 nvidia/cu13 树，再回装 cu12 的 cudnn/cusparselt/nccl/
# nvshmem 修复 torch，最后断言 torch 仍报 CUDA 12.x。
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

# 保守瘦身 toolkit：删静态库与编译期用不到的目录，供 COPY 进 final 时体积更小。
# 注意：保留 compat 之外的运行库；sgl-deep-gemm 运行期 JIT 需 nvcc + 头文件。
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

# 可运行镜像：缺省进 venv 的 python；也可 `python -m sglang.launch_server ...` 起
# serving。运行需 host NVIDIA Container Toolkit 注入 driver。
ENTRYPOINT ["/opt/codespace/frameworks/venv/bin/python"]
