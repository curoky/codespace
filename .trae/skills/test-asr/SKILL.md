---
name: test-asr
description: 构建并在本机 8 张 GPU 上运行 Codespace ASR service；当任务涉及本地 ASR image build、将模型权重持久化到 /workspace/asr-model-data、注入 Hugging Face secret、启动容器或执行真实音频 smoke test 时使用。
---

# 本地测试 ASR

从 `/workspace/codespace` 执行命令。

## 1. 构建

```bash
task check:full
podman build \
  --file platform/container/services/asr/Dockerfile \
  --tag localhost/codespace-asr:test \
  .
```

## 2. 准备运行环境

确认 8 张 80 GiB GPU 空闲，创建持久目录并更新 Hugging Face secret：

```bash
nvidia-smi --query-gpu=index,name,memory.total,memory.used --format=csv
mkdir -p /workspace/asr-model-data /workspace/asr-cache
chmod 0777 /workspace/asr-model-data /workspace/asr-cache
test -r /run/secrets/huggingface_token
podman secret create --replace \
  huggingface_token \
  /run/secrets/huggingface_token
```

## 3. 启动

模型权重直接挂载到 `/workspace/asr-model-data`；缺失权重在启动时下载：

```bash
podman run --detach --rm --name asr-test \
  --userns=keep-id:uid=5230,gid=5230 \
  --device nvidia.com/gpu=all \
  --env CUDA_VISIBLE_DEVICES=0,1,2,3,4,5,6,7 \
  --shm-size 8g \
  --publish 8080:8080 \
  --mount type=bind,source=/workspace/asr-model-data,target=/model-data \
  --mount type=bind,source=/workspace/asr-cache,target=/home/x/.cache \
  --secret huggingface_token,target=huggingface_token,uid=5230,gid=5230,mode=0400 \
  localhost/codespace-asr:test
```

观察日志，等待全部 15 个模型实例 ready：

```bash
podman logs --follow asr-test
curl --fail http://127.0.0.1:8080/health
```

## 4. 冒烟测试

```bash
uv run platform/container/services/asr/client/asr.py <audio-file> \
  --server http://127.0.0.1:8080 \
  --out /workspace/asr-test-output
```

确认输出包含 5 份 Markdown、5 份结果 JSON、`index.md`、`evidence.json`、`trace.json` 和
`trace.html`，并用 `nvidia-smi` 确认 8 张 GPU 按 placement 驻留。

## 5. 停止

```bash
podman stop asr-test
```
