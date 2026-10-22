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

Models 目录整体复制后安装依赖环境；权重不入镜像。确认实际模型环境可 import，不将构建成功
当成推理验证。检查 GPU 空闲情况；停止现有任务须有用户授权。

## Runtime

本机权重持久目录为 `/workspace/asr-model-data`，编译 cache 为 `/workspace/asr-cache`。
逐场景部署的模型集合与 placement 以
`platform/container/services/asr/deployment/<scenario>/models.env` 为准，Scheduler 使用同目录
`scheduler.yaml`。先读 `DESIGN.md` 的场景部署策略与限制，操作见 `deployment/AGENTS.md`；
每次只部署一个场景，不在
这里复制模型清单。`config.example.yaml` 展示完整模型集合，不能直接当作单场景部署输入。
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
`--shm-size 8g`，并用 `--env-file` 加载所选场景的 `ASR_MODELS` 和 `ASR_PLACEMENT`。
只注入所选 placement 需要的 GPU，并核对容器可见设备编号；不为了填满设备启动无关模型。
挂载权重到 `/model-data`、cache 到 `/home/x/.cache`；secret 用
`--secret huggingface_token,target=huggingface_token,uid=5230,gid=5230,mode=0400`。

Scheduler 加入同一 network，发布 `--publish 127.0.0.1:18080:8080`，把所选场景的
`scheduler.yaml` 只读挂载到 `/opt/asr/scheduler/scheduler.yaml`。模型不需要发布 Host port。
启动完成后逐个检查选中模型 `/health`；Scheduler `/health` 只表示 API 可用。
服务日志见 `/var/log/s6.asr-<model>.log`，用 s6 查看状态和重启。

## Validation

1. 两种 `ASR_MODELS` 分别启动，核对只有选中模型与下载依赖启动。可用 CPU VAD / Punc
   做最小选择验证；完整 placement 验证需全部目标模型同时驻留。
2. 同一常驻模型连续接受不同 `mode`，核对参数、revision、原始 evidence。
3. 重建并替换 Scheduler，确认 Models process 与启动时间保持。
4. 用 client 提交真实音频，确认每个选中 Recipe 完整输出，trace 可离线查看。
5. 用 `regression/run.py --scenario <scenario>` 从 manifest 读取方案和人数，只运行当前
   已部署场景，生成指标并检查正文、speaker、时间与并发耗时。逐场景切换部署后分别验证，
   不把其他场景请求发送给缺少其依赖的部署。

```bash
uv run platform/container/services/asr/client/asr.py <audio-file> \
  --scenario conversation --server http://127.0.0.1:18080 --out /workspace/asr-test-output
```

输出文件数量取决于选中 Recipe；每套 Markdown / JSON 和共享 index、evidence、trace
必须完整。双轨真实质量回归不能用复制单声道替代。仅清理本次测试容器和 network；
不要误停其他服务，不手工修饰 result 或 metrics。
