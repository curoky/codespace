# vLLM Service 约束

本目录构建 `ghcr.io/curoky/codespace:service-vllm`，为
Qwen3.8-Flash-Next-FP8 提供 OpenAI-compatible API。复杂构建和启动流程见
[`DESIGN.md`](DESIGN.md)。

## 不变量

- 容器名为 `codespace-service-vllm`，使用标准 Service labels，不进入 Workspace
  inventory。
- Service 使用 host network，`smoke.sh` 固定把 API 绑定到
  `127.0.0.1:${SERVE_PORT:-8003}`，不发布端口。
- 运行时通过 CDI 请求 `nvidia.com/gpu=all`，并使用 host IPC 支撑 TP8/EP8 通信。
- 模型权重不烤入镜像。Hugging Face cache 挂载到
  `~/codespace/services/vllm`，容器内路径为 `/root/.cache/huggingface`。
- 镜像不得包含 Podman socket、控制面、SSH、provider token 或 repository
  credential。
- `/opt/codespace/vllm/serve.sh` 拥有引擎参数；s6 `serve/run` 只能加载容器环境并
  exec 该脚本。

## 验证

```bash
platform/container/services/vllm/build.sh
platform/container/services/vllm/smoke.sh
```

host 必须安装 NVIDIA Container Toolkit 并配置 CDI。`smoke.sh` 会替换 vLLM 或
SGLang 的固定名称容器，因为两者同时占用全部 GPU 与端口 `8003`。

修改模型、wheel commit、CUDA backend 或启动参数时同步更新 `DESIGN.md`。修改
GPU/IPC/cache/network 形态时同步更新 `smoke.sh` 与控制面 Service 配置。
