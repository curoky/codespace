# vLLM Service

继承父目录 Service 约束，构建与运行流程见 [`DESIGN.md`](DESIGN.md)。

- 模型 cache 位于 Host，image 不包含模型、Podman socket 或 credential。
- CUDA userspace library 由 wheel 提供，image 不复制完整 CUDA Toolkit。
- runtime 固定面向单台 8x H100 Host，并与 SGLang Service 互斥。
