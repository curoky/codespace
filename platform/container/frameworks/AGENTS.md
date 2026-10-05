# Framework Images

每个子目录发布一组显式命名的 compute stack。combo 名同时编码 framework、CUDA、cuDNN、
compiler 和 Python 版本，是 build input 与 image tag 的公共 identity。

## Layout And Build

- 每个 `build.sh [combo]` 只接受安全的 combo 名，并选择同名 `<combo>.Dockerfile`；新增、删除
  或重命名 combo 时两者必须同时变化。
- Docker build context 固定为 repository root，输出 tag 是
  `ghcr.io/curoky/codespace:framework-<combo>`。
- 同一 framework 的 CUDA variants 是一个维护单元。修改 shared framework revision、Python、
  compiler 或 build flags 后构建全部 variants。
- Dockerfile 是完整可复现环境，不在启动时补装 wheel、compiler 或 CUDA component。

## Compatibility Units

- `pytorch/`：PyTorch、TorchVision、TorchAudio、CUDA/cuDNN 与 compiler 必须作为一个 ABI
  unit 更新；source build 和 smoke import 都必须使用同一组版本。
- `sglang/`：SGLang、PyTorch、SGLang kernel、deep-gemm 与 CUDA major 必须一致；CUDA 12
  variant 必须确认 dependency resolution 没有残留 CUDA 13 userspace package。
- `vllm/`：vLLM revision、对应 wheel index、PyTorch/CUDA wheel 与 build toolchain 必须同步。

## Validation

```bash
platform/container/frameworks/<framework>/build.sh <combo>
```

构建每个受影响 combo，并保留 Dockerfile 内已有的 compile/import smoke check。修改 build
script 后再运行 `task check`。
