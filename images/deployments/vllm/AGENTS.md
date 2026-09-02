# Codespace 推理 Serving 约束（vLLM）

本目录保存 host 级 **Qwen3.8-Flash-Next-FP8** 推理 serving 镜像资产的 vLLM 引擎实现，是自包含子目录，
带完整镜像资产（Dockerfile / binman.yaml / rootfs / build.sh / run.sh）。它与同级
[`sglang/`](../sglang/AGENTS.md) 结构完全对称，仅推理栈与引擎命令不同；两侧改动需互相评估同步。镜像管理方案
基本对齐 [`sidecar/`](../sidecar/AGENTS.md)：以自建 s6 init 为 PID 1，服务定义放在本目录
`rootfs/etc/s6/s6-rc.d/`，OpenAI 兼容 API 只经 host loopback 暴露。**部署与清理通常由控制面原生管理**：本镜像
作为 `deployments.vllm` 纳入 [`controller/`](../../../controller/DESIGN.md#deployment-reconcile) 的 deployment
目录，由 `hosts.<host>.deployments` 选择落到哪个 GPU host，UI 上点 Deploy/Clean 即可。也保留 `run.sh`，用于
直接登录 GPU host 时创建同名、带相同 inventory labels 的 deployment 容器。整体架构见仓库根
[`AGENTS.md`](../../../AGENTS.md)。修改本目录契约时必须同步更新本文与根 `AGENTS.md`。

模型事实：Qwen3.8-Flash-Next-FP8 是 2026-08-26 开源的多模态 MoE（125B 主模型 + 51B N-gram embedding，
单 token 激活约 6B），原生上下文 262,144，可 YaRN 扩到 1,000,000。FP8 权重约 172.78 GiB。

## 不变量

- 每个 host 最多一个推理 serving container，identity 只由 deployment id 决定：作为控制面 deployment，容器名为
  `codespace-vllm`，host 单例、不含 workspace/instance ID。不进 workspace 生命周期，不参与
  `codespace.managed=true` 的 environment inventory（只带 `codespace.deployment*` label）。一个 host 可同时声明
  vLLM 与 SGLang 两个引擎，但因二者都占用全部 GPU 和端口 8003，同一时刻只能运行一个；任一 `run.sh` 启动前
  都会删除两个引擎的现有容器。
- 单容器只跑单一引擎，即单主推理进程；无 workspace mount、SSH 服务、deploy key、repository 或 SSH 投影。
- API 使用 host network，并经 `SERVE_HOST=127.0.0.1` 只监听 host loopback（默认端口 8003，避开 sidecar 的
  8002）；不配置 `published_ports`。
- **模型权重不烤进镜像**：~172 GiB FP8 权重经 bind-mount 的 Hugging Face cache 在首次启动时由引擎拉取；该 cache
  即控制面 deployment 的托管数据目录 `~/codespace/deployments/vllm`（config volume 用 `${DEPLOYMENT_DATA}`
  占位符引用），`purge` 清理即删该目录。
- 镜像不含 Podman socket、控制面、provider token 或 repository credential。

## 引擎与镜像

vLLM 被官方列为 day-0 引擎，独立子目录、一套完整镜像资产，与 `sglang/` 互不共享文件。base image 对齐
sidecar，统一用 `docker.io/debian:trixie-slim`；与 sidecar 不同，本镜像需**自装完整 CUDA + 推理栈**（Debian 无
CUDA runtime 与推理引擎）。

| 引擎 | 镜像 tag | 推理栈 | s6 longrun |
| --- | --- | --- | --- |
| vLLM | `ghcr.io/curoky/devspace:deployments-vllm` | uv venv 从 vLLM per-commit nightly index 装 pinned nightly wheel（`${VLLM_COMMIT}` 默认 `e126687`，cu129 torch backend） | `serve` |

组装顺序对齐 sidecar：Debian slim → apt 基础包 → binman 装 standalone s6/execline 与 uv → uv 建 venv 装推理栈
→ `COPY vllm/rootfs/` → `setup-s6.sh` → s6 init。推理栈装进独立 venv `/opt/vllm/venv`（`SERVE_VENV`），`serve.sh`
显式用该 venv 的二进制（s6 生成的 init PATH 不含 venv）。venv 用 Python 3.12——GPU 推理栈生态兼容的最新版本：
vLLM 名义支持 3.10–3.13，但 flashinfer/xformers 等关键依赖的预编译 wheel 目前只稳定覆盖到 3.12，改 3.13 会
构建失败。CUDA userspace runtime 由 host 的 NVIDIA Container Toolkit 在运行期提供，推理 wheel 自带其余 CUDA
runtime 库。vLLM 不用 deep_gemm，无需 SGLang 那样的完整 CUDA Toolkit（对比见 `sglang/AGENTS.md`）。

**CUDA 版本（默认 cu129）**：vLLM 的默认 PyPI wheel 现已升到 CUDA 13（需 host 驱动 ≥580），但目标 8×H100 节点
跑 driver 535 / CUDA 12.2，故本镜像默认按 CUDA 12.x 装。Qwen3.8-Flash-Next 是 day-0 架构
（`Qwen4ExpForConditionalGeneration`），官方 recipe 明确 **PyPI 装法不支持**，只发专用镜像
`vllm/vllm-openai:qwen38-flash-next`（标注「vLLM 0.28.0+ / nightly」），任何 tagged release wheel 都不含此架构。
因此改从 vLLM 官方 **per-commit nightly index** 装 pinned nightly wheel
（`uv pip install vllm --extra-index-url https://wheels.vllm.ai/${VLLM_COMMIT}`），并加
`--extra-index-url https://download.pytorch.org/whl/${CUDA_TAG}` 解析匹配的 torch。该 commit 的 wheel pin
`torch==2.13.0`，PyTorch 只在 cu126/cu129/cu130 发布该版本、**不含 cu128**，故 `ARG CUDA_TAG` 默认 `cu129`
（H100 driver 535 跑 cu129 这类 CUDA 12.x wheel 无碍，避开 cu13 默认的 `libcudart.so.13` 报错）。CUDA 13 host 用
`CUDA_TAG=cu130` 覆盖，更老的 12.x driver 可用 `cu126`。安装命令加 `--index-strategy unsafe-best-match`：依赖跨
vLLM per-commit、PyTorch cu129 与 PyPI 三个 index，uv 默认只从首个列出某包的 index 取版本，会把 `packaging`
锁到 PyTorch index 的旧版（≤24.1），卡住 `flashinfer-python==0.6.18` 的 `packaging>=24.2`；该 flag 让 uv 跨所有
index 选最佳版本。

**day-0 架构**：模型支持已合入 main（PR [#53896](https://github.com/vllm-project/vllm/pull/53896)，commit
`e126687`）。故本镜像不 pin `VLLM_VERSION`，改用 `ARG VLLM_COMMIT`（默认 `e126687...`）从 vLLM per-commit nightly
index 装 pinned nightly wheel；待架构进入稳定 release，把它指向 tag 并可回退到 release wheel。启动报
unknown-architecture（`Qwen4ExpForConditionalGeneration`）时提升 `VLLM_COMMIT`。AMD GPU 不用本 CUDA 镜像，
改用官方 ROCm 镜像。

## s6 init

对齐 sidecar：`images/dev/script/setup-s6.sh` 从 `/opt/bm/store` 的 s6/execline 二进制编译 `/etc/s6/db`
并生成 `/etc/s6/init`，默认 runlevel `user-final`。本镜像的 `user-final` bundle 只含一个 longrun `serve`。
execline run 脚本用 `s6-envdir -Lf -- /run/s6/container_environment` 读容器环境
（含 `SERVE_MODEL`/`SERVE_HOST`/`SERVE_PORT`/`SERVE_EXTRA_ARGS`）后 `exec /opt/vllm/serve.sh`；日志写 `/var/log/serve.log`。

`serve.sh` 是 vLLM 专用启动脚本，按环境变量拼命令并 `exec` 引擎：

| 环境变量 | 默认 | 说明 |
| --- | --- | --- |
| `SERVE_MODEL` | `Qwen/Qwen3.8-Flash-Next-FP8` | 模型 id 或本地路径 |
| `SERVE_HOST` | `0.0.0.0` | 引擎监听地址；deployment 与 `run.sh` 显式设为 `127.0.0.1` |
| `SERVE_PORT` | `8003` | 容器内 OpenAI API 端口 |
| `SERVE_EXTRA_ARGS` | 空 | 追加到引擎命令的额外参数 |

优化参数已按实测 8×H100 80GB 拓扑写死在 `serve.sh` 里（不再配置化），只保留 model/host/port/extra 四个部署
相关 env，需临时改参用 `SERVE_EXTRA_ARGS` 覆盖。写死项：TEP8（`--tensor-parallel-size 8 --enable-expert-parallel`）、
Hopper 上的 `--moe-backend triton`、`--max-model-len 262144`、`--gpu-memory-utilization 0.85`、
`--no-enable-flashinfer-autotune`、`--enable-prefix-caching`、分块 prefill
（`--enable-chunked-prefill --max-num-batched-tokens 8192`）、`--max-num-seqs 256`。另开启
`--reasoning-parser qwen3` 与 `--tool-call-parser qwen3_coder`。

## 硬件与拓扑（单机 8×H100）

- 实测拓扑（`nvidia-smi`）：8×H100 80GB HBM3、compute cap 9.0（Hopper，原生 FP8 e4m3）、全互联 NVLink
  （NV18 / NVSwitch，~900 GB/s）、双 NUMA（GPU0-3→node0，GPU4-7→node1）。8×80 GB = 640 GB，FP8 权重
  ~172.78 GiB 放得下，KV/state cache 有余量但比 cookbook 的 H200 141GB 紧。
- **8×H100 的 FP8 必须用 TEP8（TP8 + Expert Parallel），不能用普通 TP8**（512 专家 MoE 布局要求）。
  vLLM 以 `--enable-expert-parallel` 开启，`serve.sh` 默认即为 TEP8。
- 全 NVLink mesh 下 TP8 all-reduce 廉价：无需 `--enable-p2p-check`，custom all-reduce 保持默认开。
- OOM 时：降 `MAX_MODEL_LEN`/`GPU_MEM_UTIL`，或设 `VLLM_PLE_CPU_OFFLOAD=1` 把 51B N-gram 表卸到主机内存
  （需大内存 host）。

## 构建与运行

镜像构建在仓库根手动执行（发布由 `.github/workflows/` 管理）：

```bash
images/deployments/vllm/build.sh         # 产出 ghcr.io/curoky/devspace:deployments-vllm
images/deployments/vllm/run.sh           # 在当前 GPU host 直接启动 vLLM
```

**标准运行路径由控制面 deployment 负责**：在 config 的 `deployments.vllm` 声明镜像与容器块，在目标 GPU host
的 `hosts.<host>.deployments` 里选中该引擎，再于 UI 点 Deploy（或
`POST /api/deployments/vllm/hosts/<host>/deploy`）。控制面按解析后 `container` 块创建容器，形态与下述要求
一致（`unless-stopped` restart policy、host network 且监听 `127.0.0.1:<port>`）。直接登录 GPU host 时也可运行
`run.sh`；脚本创建同名并带标准 deployment labels 的容器，控制面可继续识别和清理。与 sidecar 不同处（推理 serving 专属，
均为新增 mount/device 例外，均在 deployment `container` 块声明）：

- 经 CDI `--device nvidia.com/gpu=all` 请求本机全部 GPU（`container.devices`）；TP8/EP8 多进程通信需要充足的
  `/dev/shm`，用 `--ipc host`（`container.ipc: host`）直接复用宿主共享内存，不再设置只作用于私有 IPC
  namespace 的 `container.shm_size`。Deployment 不继承开发默认，无需反向清除 `cap_add`/`security_opt`。
- Hugging Face cache 用 `${DEPLOYMENT_DATA}:/root/.cache/huggingface` volume 绑到托管数据根
  `~/codespace/deployments/vllm`，首次启动拉取 ~172 GiB 权重到该目录，需 ≥~200 GiB 空闲空间；容器内经
  `HF_HOME=/root/.cache/huggingface` 指向它。gated/加速下载可先在 `container.environment` 或宿主注册 `HF_TOKEN`。

host 前置：NVIDIA Container Toolkit 并配好 CDI（`nvidia.com/gpu` 设备）。

## 目录

| 路径 | 职责 |
| --- | --- |
| `AGENTS.md` | 本文，vLLM 引擎契约 |
| `Dockerfile` | 基于 `debian:trixie-slim` 自装 CUDA/推理栈 + s6 + 本目录 rootfs |
| `binman.yaml` | s6/execline standalone profile + uv link |
| `rootfs/opt/vllm/serve.sh` | vLLM 专用启动脚本，按环境变量拼引擎命令 |
| `rootfs/etc/s6/s6-rc.d/serve` | s6 longrun |
| `rootfs/etc/s6/s6-rc.d/user-final` | 默认 runlevel bundle，`contents.d/serve` 标记该 longrun |
| `build.sh` | 从仓库根构建本地镜像 `deployments-vllm` |
| `run.sh` | 在 GPU host 直接替换并启动对应 deployment 容器 |

## 变更规则

- 与 `sglang/` 保持结构对称：一侧新增文件/knob 时评估另一侧是否需同步。
- 不烤入模型权重；不引入 Podman socket、控制面、provider token 或 repository credential。
- 新增引擎参数优先经 `serve.sh` 环境变量暴露，不写死在 s6 run 脚本；引擎命令随官方 recipe 变化时更新
  `serve.sh` 并同步本文。
- 容器运行形态（GPU/IPC、HF cache volume、网络和端口）改动必须同时更新 config 的 `deployments.vllm`、
  `run.sh` 与 [`controller/AGENTS.md`](../../../controller/AGENTS.md)。
- day-0 架构支持随 Dockerfile `ARG` 演进：当前无含此架构的 tagged release，用 `VLLM_COMMIT`（vLLM per-commit
  nightly index）锁定到含 Qwen3.8-Flash-Next 的 commit，变更时同步本文表格。
- 影响跨组件契约时同步根 [`AGENTS.md`](../../../AGENTS.md)。
