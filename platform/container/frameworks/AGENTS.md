# Framework Images

## Scope

发布显式命名、可复现的 compute stack。combo 名同时编码 framework、CUDA、cuDNN、
compiler 和 Python 版本，是 build input 与 image tag 的公共 identity；具体组合由对应
Dockerfile 拥有，不在文档维护第二份版本清单。

## Contracts

- 每个 build script 只接受安全的 combo 名，并选择同名 `<combo>.Dockerfile`；新增、删除
  或重命名 combo 时同步入口与配方，不能让 tag 指向另一套环境。
- Docker build context 固定为 repository root，输出 tag 是
  `ghcr.io/curoky/codespace:framework-<combo>`。
- 同一 framework 的 CUDA variants 是一个维护单元。修改 shared framework revision、Python、
  compiler 或 build flags 后构建全部 variants。
- Dockerfile 是完整可复现环境，不在启动时补装 wheel、compiler 或 CUDA component。

## Pitfalls

- [pytorch](pytorch/)：PyTorch、TorchVision、TorchAudio、CUDA/cuDNN 与 compiler 必须作为一个 ABI
  unit 更新；source build 和 smoke import 都必须使用同一组版本。
- [sglang](sglang/)：SGLang、PyTorch、SGLang kernel、deep-gemm 与 CUDA major 必须一致；CUDA 12
  variant 必须确认 dependency resolution 没有残留 CUDA 13 userspace package。
- [vllm](vllm/)：vLLM revision、对应 wheel index、PyTorch/CUDA wheel 与 build toolchain 必须同步。

## Validation

```bash
platform/container/frameworks/<framework>/build.sh <combo>
```

构建每个受影响 combo，并保留 Dockerfile 内已有的 compile/import smoke check。
