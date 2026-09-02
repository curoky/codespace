# SGLang Service

继承父目录 Service 约束，构建与运行流程见 [`DESIGN.md`](DESIGN.md)。

- Dockerfile、binman manifest 与 `serve.sh` 是依赖、模型和启动参数的 source of truth。
- 模型 cache 位于 Host，image 不包含模型、Podman socket 或 credential。
- 构建、运行或 GPU 边界变化时同步更新 `DESIGN.md`、smoke script 和控制面配置。
