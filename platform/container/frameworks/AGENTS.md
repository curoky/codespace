# Framework 镜像约束

本目录保存从源码构建的 PyTorch、vLLM 与 SGLang 镜像。Framework 镜像提供可直接
`import` 的运行环境，不启动 s6，也不承担 OpenAI API Service。

## 命名

- 每个 `CUDA × framework × compiler × Python` 组合使用独立 Dockerfile：
  `<project><version>-cu<cuda>-cudnn<major>-gcc<major>-py<version>.Dockerfile`。
- 文件名去掉 `.Dockerfile` 后得到 `<combo>`；镜像 tag 固定为
  `ghcr.io/curoky/codespace:framework-<combo>`。
- 版本值以各 Dockerfile 的 `ARG` 为事实来源，不在本文维护重复清单。
- 新增组合必须新增 Dockerfile，不得复用或覆盖已有组合。

## 构建契约

- 构建 context 固定为仓库根；每个 project 的 `build.sh` 接受零或一个 `<combo>` 参数，
  无参数时构建该项目的 CUDA 12.9 默认组合。
- PyTorch 与 vLLM 可用 `MAX_JOBS`、`NVCC_THREADS` 调整编译并发；默认面向高配远端
  rootful Podman host。SGLang 当前只编译 Python 主包，GPU kernel 使用官方 wheel。
- builder 必须使用与 CUDA toolkit 匹配的 Ubuntu CUDA devel image。不要在
  `debian:trixie-slim` final stage 编译 CUDA 源码，避免 glibc 与 nvcc 头文件冲突。
- final stage 只复制瘦身后的 toolkit、`/opt/codespace/frameworks/venv` 与运行所需源码，
  默认 entrypoint 是该 venv 的 Python。
- vLLM 使用 editable install，final stage 必须保留
  `/opt/codespace/frameworks/src/vllm`。
- vLLM 的 `--no-build-isolation` 路径必须预装 `setuptools_rust` 等构建后端依赖。

## Hardware

- 当前镜像面向 8x H100：PyTorch 使用 `TORCH_CUDA_ARCH_LIST=9.0`，vLLM/SGLang 使用
  `9.0a` 以启用 Hopper 专属指令。
- CUDA 12.9 产物可在目标 driver 535 host 上运行；CUDA 13 产物要求 driver 580 或更新版本。
- 运行时由 NVIDIA Container Toolkit 注入 driver，并通过 CDI 请求
  `nvidia.com/gpu=all`。

## 验证

```bash
platform/container/frameworks/pytorch/build.sh
platform/container/frameworks/sglang/build.sh
platform/container/frameworks/vllm/build.sh
MAX_JOBS=8 NVCC_THREADS=2 \
  platform/container/frameworks/vllm/build.sh \
  vllm0.28-cu13.0.1-cudnn9-gcc12-py3.12
```

修改 stage 结构、toolkit 裁剪或编译环境时，必须评估三个 project 是否需同步。模型或
framework 版本、CUDA、compiler、Python 任一维度变化，都必须反映在文件名与 tag 中。
