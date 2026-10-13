# Deployment Maintenance

本目录维护单场景部署输入与 GPU pipeline 图片。架构、模型一览、方案模型组合、GPU
分配和并发取舍统一见 [../DESIGN.md](../DESIGN.md)；不在本文件复制设计表格。

## Contracts

- `deployment/<scenario>/models.env` 定义该场景全部 Recipe 的模型并集与 GPU placement。
- 同目录 `scheduler.yaml` 只登记同一集合的模型地址和固定实例容量。
- 每次选择一个场景，所有目标模型 ready 后再提交请求；切换场景先等当前请求完成。
- `figures/` 的 PNG / SVG 是当前部署的依赖示意。改变 Recipe、容量或 placement 后同步
  `DESIGN.md` 表格和图片；一次性生成脚本放仓库外。
- 模型与方案清单以源码和配置为准，文档中的已测版本和显存需有明确测量口径。

## Podman

以下以朗读为例，在仓库根目录执行。将两个配置路径一起替换为目标场景。只注入已分配的
GPU；环境文件中的设备编号必须与容器可见 GPU 编号一致，换用其他物理卡时先核对映射。
`config.example.yaml` 的完整模型集合展示全模型参考布局，逐场景部署使用本目录输入。

预先准备持久权重、cache、Podman secret 和专用 network；真实路径与 secret 不写入配置
文件。参考验证环境的两个持久目录分别为 `/workspace/asr-model-data` 和
`/workspace/asr-cache`，secret 名称为 `huggingface_token`。

```bash
podman network create asr-scenario
podman run --detach --name asr-models \
  --network asr-scenario --network-alias codespace-service-asr-models \
  --userns=keep-id:uid=5230,gid=5230 \
  --device nvidia.com/gpu=0 --device nvidia.com/gpu=1 \
  --device nvidia.com/gpu=2 --device nvidia.com/gpu=3 \
  --shm-size 8g --pids-limit -1 \
  --env-file platform/container/services/asr/deployment/narration/models.env \
  --volume /workspace/asr-model-data:/model-data \
  --volume /workspace/asr-cache:/home/x/.cache \
  --secret huggingface_token,target=huggingface_token,uid=5230,gid=5230,mode=0400 \
  localhost/codespace-asr-models:test

podman run --detach --name asr-scheduler \
  --network asr-scenario --publish 127.0.0.1:18080:8080 \
  --volume "$PWD/platform/container/services/asr/deployment/narration/scheduler.yaml:/opt/asr/scheduler/scheduler.yaml:ro" \
  localhost/codespace-asr-scheduler:test

uv run platform/container/services/asr/client/asr.py <audio-file> \
  --scenario narration --parallel 1 --server http://127.0.0.1:18080 --out <output-directory>
```

分轨、混录与会议额外注入 GPU 4–7。使用 Codespace 控制面时，将所选环境文件
的两项写入 `asr-models.container.environment`，并把对应 `scheduler.yaml` 作为只读 volume
挂载到 Scheduler 的同名路径；mount、secret、GPU 和 publication 仍由控制面配置拥有。

提交前逐个检查所选模型的 `/health`。Scheduler `/health` 只说明 API 可用；其默认场景入口
仍包含四个场景，调用方必须选择与当前部署一致的场景，缺失模型直接报错。

## Validation

`tests/test_deployment.py` 从 Recipe 源码核对场景模型并集、环境文件、GPU placement 和
Scheduler 配置的一致性。配置变更运行 `task check:full`，然后用 `test-asr` skill 验证选中
模型全部 ready、同时驻留、实际调用重叠、显存峰值、完整结果及请求耗时。

每次只验证一个场景，运行真实 fixture 时明确传入 `--scenario`，不要用全部场景回归命令
向只部署一个场景的模型集合提交请求。只清理本次验证的容器和 network。
