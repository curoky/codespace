# SGLang Service Design

## Image Build

目标模型依赖尚未进入稳定发行版的能力，因此 image 从固定 upstream revision
构建 SGLang。revision、backend 与 wheel 版本只在 Dockerfile 中维护。

FP8 路径会在 runtime JIT 编译 kernel，因此 final image 必须保留 compiler、
header 和动态链接库。CUDA builder 先删除 JIT 不需要的静态库与开发资产，
再把精简后的 toolkit 复制进 final stage；不能改成只依赖 inference wheel
的形态。

upstream 依赖可能解析到不同 CUDA backend。安装层负责把 torch、GPU kernel 与
NVIDIA library 归一到同一 backend，并以 compile/import assertion 验证结果。venv
必须自包含，删除 build cache 后不能留下指向 cache 的 hardlink。

## Runtime

s6 只管理 serving longrun。`serve.sh` 固化目标 Host 的并行、内存、attention 与
speculative decoding profile，并显式暴露 CUDA toolchain 给 JIT；可配置项只用于
部署相关的 model 与 listener。

模型 cache 由 managed Service data 提供。部署必须申请完整 GPU 与 IPC 能力，并
遵守父目录的网络和 vLLM 互斥约束。
