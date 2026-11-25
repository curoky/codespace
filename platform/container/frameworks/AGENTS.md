# Framework Images

## Scope

发布显式命名的 compute stack；combo 编码 framework/CUDA/cuDNN/compiler/Python，是
build input 与 image tag 的公共 identity。组合、配方与入口由各 framework 的 Dockerfile/
build.sh 拥有，不另维护版本/tag 清单。

## Contracts

- build 只接受安全 combo 名并选择同名 Dockerfile；增删/重命名同步入口与配方。
- 同 framework 的 CUDA variants 是维护单元，shared revision/toolchain/build flags 变化
  构建全部 variants；Dockerfile 完整可复现，不在启动时补装环境。

## Pitfalls

- [PyTorch](pytorch/) 与 TorchVision/TorchAudio/CUDA/cuDNN/compiler 作为 ABI unit 更新，
  source build 与 smoke import 使用同一组合。
- [SGLang](sglang/) 与 PyTorch/kernel/deep-gemm/CUDA major 一致，CUDA 12 variant 不留
  resolver 带入的 CUDA 13 userspace package。
- [vLLM](vllm/) revision/wheel index/PyTorch CUDA wheel/build toolchain 同步。

## Validation

按对应 build.sh 构建全部受影响 combo，保留配方已有 compile/import smoke check；非行为
变化按根文档检查，不要求重建矩阵。
