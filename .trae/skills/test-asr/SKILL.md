---
name: test-asr
description: 构建、准备权重并在本机 GPU 上运行 Codespace ASR service；当任务涉及本地 ASR image build、模型权重下载到 /workspace/model-data、Podman 权重挂载、容器启动、日志排查或真实音频 smoke test 时使用。
---

# 本地测试 ASR

所有命令从 `/workspace/codespace` 执行。image 不含模型权重；本地测试先手动下载到 Host 的
`/workspace/model-data`，再只读挂载到容器 `/model-data`。不要把权重写回 Git 仓库。

## 构建镜像

先运行完整代码门禁，再构建不含权重的 image：

```bash
task check:full
podman build \
  --file platform/container/services/asr/Dockerfile \
  --tag localhost/codespace-asr:test \
  .
```

如果 rootless build 报外层 cgroup device 路径不存在，保留同一 Podman storage 并改用：

```bash
podman build \
  --isolation=chroot \
  --format docker \
  --file platform/container/services/asr/Dockerfile \
  --tag localhost/codespace-asr:test \
  .
```

构建命令不传 Hugging Face secret。重建 image 不应修改或重新下载 `/workspace/model-data`。

## Runtime Preflight

本服务按逻辑序号使用 6 张 80 GiB GPU；Host 可以暴露更多卡，但 placement 只会使用前六张。
先确认至少六张卡空闲，再验证 rootless Podman 的 CDI 和 bind mount 视图：

```bash
nvidia-smi --query-gpu=index,name,memory.total,memory.used --format=csv
mkdir -p /workspace/model-data
podman run --rm \
  --device nvidia.com/gpu=all \
  --entrypoint nvidia-smi \
  localhost/codespace-asr:test \
  -L
podman run --rm \
  --entrypoint test \
  --mount type=bind,source=/workspace/model-data,target=/model-data,readonly \
  localhost/codespace-asr:test \
  -d /model-data
```

CDI 检查失败时先在 Host 修复 NVIDIA CDI spec；bind 检查报 `statfs ... no such file or
directory` 表示 Podman service 的 mount namespace 看不到 `/workspace`，应在该 mount 已存在
后重启 Podman service。不能立即修复 namespace 时，可以把持久权重直接放入
`asr-model-data` named volume，并在下文所有命令中把 bind 行替换为：

```bash
podman volume exists asr-model-data || podman volume create asr-model-data
```

```text
--mount type=volume,source=asr-model-data,target=/model-data
```

本地临时手工映射 `/dev/nvidia*` 只能用于定位 CDI 问题，不能写进生产配置或提交到项目。

## 准备模型权重

先确认 `/run/secrets/huggingface_token` 存在且当前用户可读，并已接受 gated model 的访问条件。
创建持久目录，然后用刚构建的环境手动拉取全部固定 snapshot：

```bash
mkdir -p /workspace/model-data
podman run --rm \
  --entrypoint bash \
  --env HOME=/home/x \
  --env HF_TOKEN_PATH=/run/secrets/huggingface_token \
  --mount type=bind,source=/workspace/model-data,target=/model-data \
  --mount type=bind,source=/run/secrets/huggingface_token,target=/run/secrets/huggingface_token,readonly \
  localhost/codespace-asr:test \
  -euo pipefail -c 'for script in /opt/asr/models/*/download_model.sh; do "$script"; done'
```

`hf download` 会利用各模型目录中的 metadata 增量补齐，并在成功后写入 `.revision` marker；
容器启动时 marker 匹配便立即跳过自动下载。不要为了更新一个模型删除整个
`/workspace/model-data`。只准备单个模型时，把最后的循环替换为该模型的固定脚本，例如：

```bash
/opt/asr/models/qwen3-asr-1.7b/download_model.sh
```

## 启动服务

完整 server 需要 placement 声明的 6 张空闲 80 GiB GPU。启动前完成上述 preflight，再运行：

```bash
mkdir -p /workspace/asr-data
podman run --rm --name asr-test \
  --device nvidia.com/gpu=all \
  --shm-size 8g \
  --publish 8080:8080 \
  --mount type=bind,source=/workspace/model-data,target=/model-data,readonly \
  --mount type=bind,source=/workspace/asr-data,target=/data/asr \
  localhost/codespace-asr:test
```

rootless Podman 会把容器 UID 映射成 Host subuid。Host bind 目录必须预先允许容器进程创建请求
子目录；本地测试可对新建的专用输出目录执行 `chmod 0777 /workspace/asr-data`，不要递归修改已有
回归资产、模型目录或仓库，也不需要用 `sudo chown`。生产部署继续使用控制面创建的持久卷。

`--shm-size 8g` 是 FireRed TP / NCCL 的必要条件；默认约 64 MiB 的 `/dev/shm` 不足。正常
部署也必须使用 `config.example.yaml` 中 ASR Service 的相同配置。

不要增加请求期模型启停参数。容器启动时会先检查每个模型的 revision marker，再按
`server/server.yaml` 的逻辑 placement 依次启动全部模型；`GET /health` 只有全部模型 ready
后才可用。另开终端观察：

```bash
podman logs --follow asr-test
curl --fail http://127.0.0.1:8080/health
```

## 转写冒烟测试

使用真实短音频和独立输出目录；除非用户明确允许，不覆盖已有结果：

```bash
uv run platform/container/services/asr/client/asr.py <audio-file> \
  --server http://127.0.0.1:8080 \
  --out /workspace/asr-test-output
```

验证五份 Markdown、五份结果 JSON、`index.md`、`evidence.json` 和 `trace.json`。同时核对
六卡驻留余量、其余可见 GPU 未被占用、TP/NCCL、first pass 与 review 的跨模型时间区间
确有重叠，以及日志中无截断或模型重启；模拟测试和 image build 不能替代这些真实 GPU
检查。

结束时用 `Ctrl-C` 停止前台容器。不要删除 `/workspace/model-data`，它是后续 build 和测试
复用的持久权重缓存。
