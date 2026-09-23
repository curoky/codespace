# Framework Images

- 每个 `build.sh` 的 combo 必须对应同名 Dockerfile；修改后构建受影响的每个 combo。
- `pytorch/` 将 PyTorch、TorchVision 与 TorchAudio revision 作为一个 compatibility
  unit，CUDA variants 必须同步更新。
- `sglang/` 的 SGLang、PyTorch、kernel 与 deep-gemm 必须使用同一 CUDA major；CUDA 12
  variant 必须清除解析得到的 CUDA 13 userspace package。
- `vllm/` 的 CUDA variants 必须同步更新 vLLM revision、PyTorch wheels 与 build
  toolchain。
