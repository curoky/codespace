# SGLang Service

继承父目录 Service 约束，构建与运行流程见 [`DESIGN.md`](DESIGN.md)。

- 模型 cache 位于 Host，image 不包含模型、Podman socket 或 credential。
- image 必须保留 `deep_gemm` 运行时 JIT 所需的 CUDA compiler 与 header。
- runtime 固定面向单台 8x H100 Host，并与 vLLM Service 互斥。
