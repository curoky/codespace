---
name: test-asr
description: 构建并验证本地 ASR Scheduler 与 Models 镜像、s6 模型选择和真实音频回归。
---

# Local ASR Validation

从 `/workspace/codespace` 执行。先读
`platform/container/services/asr/AGENTS.md` 与 `regression/AGENTS.md`。

## Build

```bash
task check:full
podman build --file platform/container/services/asr/models/Dockerfile \
  --tag localhost/codespace-asr-models:test .
podman build --file platform/container/services/asr/scheduler/Dockerfile \
  --tag localhost/codespace-asr-scheduler:test .
```

模型依赖环境与 serving 分层构建；权重不入镜像。确认实际模型环境可 import，不将构建成功
当成推理验证。检查 GPU 空闲情况；停止现有任务须有用户授权。

## Runtime

本机权重持久目录为 `/workspace/asr-model-data`，编译 cache 为 `/workspace/asr-cache`。
部署输入的模型集合与 placement 以 `config.example.yaml` 为准，不在这里复制另一份清单。
Hugging Face secret 来自 `/run/secrets/huggingface_token`，不打印 token。

```bash
nvidia-smi --query-gpu=index,name,memory.total,memory.used --format=csv
mkdir -p /workspace/asr-model-data /workspace/asr-cache
chmod 0777 /workspace/asr-model-data /workspace/asr-cache
podman secret create --replace huggingface_token /run/secrets/huggingface_token
podman network create asr-test-network
```

Models 容器指定 `--network asr-test-network`、
`--network-alias codespace-service-asr-models`、`--userns=keep-id:uid=5230,gid=5230`、
`--device nvidia.com/gpu=all`、`--shm-size 8g`，并传入 `ASR_MODELS` 和 `ASR_PLACEMENT`。
挂载权重到 `/model-data`、cache 到 `/home/x/.cache`；secret 用
`--secret huggingface_token,target=huggingface_token,uid=5230,gid=5230,mode=0400`。

Scheduler 加入同一 network，发布 `--publish 18080:8080`。模型不需要发布 Host port。
启动完成后逐个检查选中模型 `/health`；Scheduler `/health` 只表示 API 可用。
服务日志见 `/var/log/s6.asr-<model>.log`，用 s6 查看状态和重启。

## Validation

1. 两种 `ASR_MODELS` 分别启动，核对只有选中模型与下载依赖启动。可用 CPU VAD / Punc
   做最小选择验证；完整 placement 验证需全部目标模型同时驻留。
2. 同一常驻模型连续接受不同 `mode`，核对参数、revision、原始 evidence。
3. 重建并替换 Scheduler，确认 Models process 与启动时间保持。
4. 用 client 提交真实音频，确认每个选中 Recipe 完整输出，trace 可离线查看。
5. 用 `regression/run.py` 从 manifest 读取方案和人数，运行所有场景并生成指标，检查正文、
   speaker、时间与并发耗时。

```bash
uv run platform/container/services/asr/client/asr.py <audio-file> \
  --scenario conversation --server http://127.0.0.1:18080 --out /workspace/asr-test-output
```

输出文件数量取决于选中 Recipe；每套 Markdown / JSON 和共享 index、evidence、trace
必须完整。双轨真实质量回归不能用复制单声道替代。仅清理本次测试容器和 network；
不要误停其他服务，不手工修饰 result 或 metrics。
