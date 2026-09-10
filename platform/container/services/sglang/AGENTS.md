# SGLang Service

继承父目录 Service 约束，构建与运行流程见 [`DESIGN.md`](DESIGN.md)。

- image 不包含模型、Podman socket 或 credential，模型 cache 由 Host 持久化。
- final image 必须保留 `deep_gemm` JIT 所需的 CUDA toolchain。
- 当前 serving profile 独占单台 8x H100 Host；参数变化以 `serve.sh` 为准。
