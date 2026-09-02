# Codespace LLM Serving 约束（SGLang）

本目录保存 host 级 **Qwen3.8-Flash-Next-FP8** 推理 serving 镜像资产的 SGLang 引擎实现，是自包含子目录，
带完整镜像资产（Dockerfile / binman.yaml / rootfs / build.sh / run.sh）。它与同级
[`vllm/`](../vllm/AGENTS.md) 结构完全对称，仅推理栈与引擎命令不同；两侧改动需互相评估同步。镜像管理方案
基本对齐 [`sidecar/`](../sidecar/AGENTS.md)：以自建 s6 init 为 PID 1，服务定义放在本目录
`rootfs/etc/s6/s6-rc.d/`，OpenAI 兼容 API 只经 host loopback 暴露。**部署与清理通常由控制面原生管理**：本镜像
作为 `deployments.llm-sglang` 纳入 [`controller/`](../../../controller/DESIGN.md#deployment-reconcile) 的 deployment
目录，由 `hosts.<host>.deployments` 选择落到哪个 GPU host，UI 上点 Deploy/Clean 即可。也保留 `run.sh`，用于
直接登录 GPU host 时创建同名、带相同 inventory labels 的 deployment 容器。整体架构见仓库根
[`AGENTS.md`](../../../AGENTS.md)。修改本目录契约时必须同步更新本文与根 `AGENTS.md`。

模型事实：Qwen3.8-Flash-Next-FP8 是 2026-08-26 开源的多模态 MoE（125B 主模型 + 51B N-gram embedding，
单 token 激活约 6B），原生上下文 262,144，可 YaRN 扩到 1,000,000。FP8 权重约 172.78 GiB。

## 不变量

- 每个 host 最多一个 LLM serving container，identity 只由 deployment id 决定：作为控制面 deployment，容器名为
  `codespace-llm-sglang`，host 单例、不含 workspace/instance ID。不进 workspace 生命周期，不参与
  `codespace.managed=true` 的 environment inventory（只带 `codespace.deployment*` label）。一个 host 可同时声明
  vLLM 与 SGLang 两个引擎，但因二者都占用全部 GPU 和端口 8003，同一时刻只能运行一个；任一 `run.sh` 启动前
  都会删除两个引擎的现有容器。
- 单容器只跑单一引擎，即单主推理进程；无 workspace mount、SSH 服务、deploy key、repository 或 SSH 投影。
- API 使用 host network，并经 `LLM_HOST=127.0.0.1` 只监听 host loopback（默认端口 8003，避开 sidecar 的
  8002）；不配置 `published_ports`。
- **模型权重不烤进镜像**：~172 GiB FP8 权重经 bind-mount 的 Hugging Face cache 在首次启动时由引擎拉取；该 cache
  即控制面 deployment 的托管数据目录 `~/codespace/deployments/llm-sglang`（config volume 用 `${DEPLOYMENT_DATA}`
  占位符引用），`purge` 清理即删该目录。
- 镜像不含 Podman socket、控制面、provider token 或 repository credential。

## 引擎与镜像

SGLang 被官方列为 day-0 引擎，独立子目录、一套完整镜像资产，与 `vllm/` 互不共享文件。base image 对齐
sidecar，统一用 `docker.io/debian:trixie-slim`；与 sidecar 不同，本镜像需**自装完整 CUDA + 推理栈**（Debian 无
CUDA runtime 与推理引擎）。

| 引擎 | 镜像 tag | 推理栈 | s6 longrun |
| --- | --- | --- | --- |
| SGLang | `ghcr.io/curoky/devspace:llm-sglang` | uv venv 从 PR 源码装（`${SGLANG_REF}` 默认 `pull/36497/head`，cu129 kernel） | `llm` |

组装顺序对齐 sidecar：Debian slim → apt 基础包（含 `git`）→ binman 装 standalone s6/execline 与 uv → uv 建 venv
装推理栈 → `COPY sglang/rootfs/` → `setup-s6.sh` → s6 init。推理栈装进独立 venv `/opt/llm/venv`（`LLM_VENV`），
`serve.sh` 显式用该 venv 的二进制（s6 生成的 init PATH 不含 venv）。venv 用 Python 3.12——GPU 推理栈生态兼容的
最新版本：SGLang 的 GPU wheel 与 flashinfer/xformers 等关键依赖的预编译 wheel 目前只稳定覆盖到 3.12，改 3.13 会
构建失败。CUDA userspace runtime 由 host 的 NVIDIA Container Toolkit 在运行期提供，推理 wheel 自带其余 CUDA
runtime 库。

**SGLang 需完整 CUDA Toolkit（nvcc + 头文件）**：SGLang 的 FP8 路径依赖 `sgl-deep-gemm`，其 kernel 在
`import deep_gemm` 时 **JIT 编译**，`find_cuda_home()` 会断言存在含 nvcc 的真实 CUDA 安装，否则启动即崩
（`AssertionError: cuda_home is not None`）。Container Toolkit 只注入 host *driver*（libcuda.so）、wheel 只带
*runtime* 库，二者都不含 nvcc/dev 头。因此本镜像用 multi-stage：从 NVIDIA 官方 CUDA devel 镜像
（`ARG CUDA_DEVEL_IMAGE`，默认 `nvidia/cuda:12.9.1-devel-ubuntu24.04`）`COPY --from` 仅拷 toolkit 目录
`/usr/local/cuda-12.9`（`ARG CUDA_HOME_DIR`，不含 driver、不含 distro 库），设 `CUDA_HOME` 指向它，且
`serve.sh` 内再 export 一次做兜底（防 s6 环境快照未透传 Dockerfile ENV）。devel 镜像虽基于 ubuntu，但 toolkit
目录与 OS 无关，可直接用于 debian:trixie base。`CUDA_HOME_DIR` 须与 devel 镜像的 CUDA 版本对齐。（vLLM 不用
deep_gemm，无需此 toolkit，对比见 `vllm/AGENTS.md`。）**瘦身**：cuda stage 在 COPY 前删掉 JIT 用不到的部分——
静态库 `*.a`（~3.7GiB，deep_gemm 只动态链接）、NPP 图像库、doc/share/src/compute-sanitizer/extras/compat，把
toolkit 从 ~7.3GiB 压到 ~2.9GiB（须在 stage 内删，COPY 后再删只会加 whiteout 层不缩小镜像）。**cu13 残留清理**：
装 sglang（其依赖请求 cu13 flavor）后再 force-reinstall cu129 torch 三件套，会残留整套 `nvidia-*-cu13`
（~2GiB，`nvidia/cu13/` + 与 cu12 共用目录的重复库），而 driver-535 host 永远加载不了 cu13。安装 RUN 末尾卸载
所有版本为 13.x 或名字以 `_cu13` 结尾的 nvidia 包（保留 `nvidia_ml_py`）并删 `nvidia/cu13/`；因 cu12/cu13 共用
cudnn/cusparselt/nccl/nvshmem 目录，卸 cu13 会带走 torch 需要的共享 `.so`，故随后 `--reinstall` 补回这四个 cu12
库修复 torch，末尾 assert `torch.version.cuda` 仍为 12.x。venv 由此从 ~13GiB 降到 ~11GiB。

**CUDA 版本（默认 cu129）**：SGLang 的默认 PyPI wheel 现已升到 CUDA 13（需 host 驱动 ≥580），但目标 8×H100
节点跑 driver 535 / CUDA 12.2，故本镜像默认按 CUDA 12.x 装。SGLang 走官方 cu129 recipe（对齐 docs.sglang.io
安装文档与上游 `docker/Dockerfile` 的 torch_deps 序列）——从 PR 源码装 `sglang` 后，依次从 cu129 index
force-reinstall **pinned torch 三件套**（`ARG TORCH_SPEC`，默认
`torch==2.13.0 torchvision==0.28.0 torchaudio==2.11.0`；裸 `torch` 会拉到 cu13 默认版）、`sglang-kernel`
（pip 名，cu129 wheel 内部为 `sglang_kernel`）与 `sgl-deep-gemm`（`--no-deps`），`ARG CUDA_TAG` 选 index。
CUDA 13 host 用 `CUDA_TAG=cu130` 覆盖（并设 `TORCH_SPEC="torch torchvision torchaudio"`）。SGLang 不装 `[all]`
extra，改用官方 recipe 的独立 kernel 包。

**day-0 架构（尚无含 Qwen3.8-Flash-Next 的 SGLang release）**：SGLang 目前**没有任何含此架构的 tagged
release**，PyPI 装不到；按官方 cookbook，模型支持在 PR
[#36497](https://github.com/sgl-project/sglang/pull/36497)，故本镜像不 pin `SGLANG_VERSION`，改用
`ARG SGLANG_REF`（默认 `pull/36497/head`）从源码 clone 该 PR 后 `uv pip install -e python`（Dockerfile 因此新增
apt `git`）。该源码树用 setuptools-rust 内嵌 3 个 PyO3 crate（`sglang-grpc`/`sglang-mm`/`sglang-server`），
editable 装会调 `cargo`；slim 镜像无 Rust 工具链，故 `ARG SGLANG_BUILD_RUST_EXTS=none` 跳过——它们只支撑
gRPC/multimodal/model-gateway 入口，`sglang.launch_server`（OpenAI HTTP）不依赖。需要这些入口时设 `all` 并自备
cargo。待架构进入 release，把 `SGLANG_REF` 指向该 tag 并可回退到 `uv pip install sglang`。

## s6 init

对齐 sidecar：`images/dev/script/setup-s6.sh` 从 `/opt/bm/store` 的 s6/execline 二进制编译 `/etc/s6/db`
并生成 `/etc/s6/init`，默认 runlevel `user-final`。本镜像的 `user-final` bundle 只含一个 longrun `llm`。
execline run 脚本用 `s6-envdir -Lf -- /run/s6/container_environment` 读容器环境
（含 `LLM_MODEL`/`LLM_HOST`/`LLM_PORT`/`LLM_EXTRA_ARGS`）后 `exec /opt/llm/serve.sh`；日志写 `/var/log/llm.log`。

`serve.sh` 是 SGLang 专用启动脚本，按环境变量拼命令并 `exec` 引擎：

| 环境变量 | 默认 | 说明 |
| --- | --- | --- |
| `LLM_MODEL` | `Qwen/Qwen3.8-Flash-Next-FP8` | 模型 id 或本地路径 |
| `LLM_HOST` | `0.0.0.0` | 引擎监听地址；deployment 与 `run.sh` 显式设为 `127.0.0.1` |
| `LLM_PORT` | `8003` | 容器内 OpenAI API 端口 |
| `LLM_EXTRA_ARGS` | 空 | 追加到引擎命令的额外参数 |

优化参数已按实测 8×H100 80GB 拓扑写死在 `serve.sh` 里（不再配置化），只保留 model/host/port/extra 四个部署
相关 env，需临时改参用 `LLM_EXTRA_ARGS` 覆盖。写死项：TEP8（`--tp-size 8 --ep-size 8`）、
`--context-length 262144`、`--mem-fraction-static 0.85`、`--chunked-prefill-size 8192`、
`--max-running-requests 96`、GDN+QSA 必需的 `--linear-attn-*-backend flashinfer` + `--mamba-ssm-dtype bfloat16`、
in-checkpoint MTP head 的 NEXTN speculative decoding。另开启 `--reasoning-parser qwen3` 与
`--tool-call-parser qwen3_coder`。

## 硬件与拓扑（单机 8×H100）

- 实测拓扑（`nvidia-smi`）：8×H100 80GB HBM3、compute cap 9.0（Hopper，原生 FP8 e4m3）、全互联 NVLink
  （NV18 / NVSwitch，~900 GB/s）、双 NUMA（GPU0-3→node0，GPU4-7→node1）。8×80 GB = 640 GB，FP8 权重
  ~172.78 GiB 放得下，KV/state cache 有余量但比 cookbook 的 H200 141GB 紧。
- **8×H100 的 FP8 必须用 TEP8（TP8 + Expert Parallel），不能用普通 TP8**（512 专家 MoE 布局要求）。
  SGLang 以 `--ep-size` 开启，`serve.sh` 默认即为 TEP8。
- 全 NVLink mesh 下 TP8 all-reduce 廉价：无需 `--enable-p2p-check`，custom all-reduce 保持默认开。
- `serve.sh` 针对 80 GB 写死了适配参数：`--mem-fraction-static 0.85` 给 Mamba/GDN state cache 与 activation 留
  余量、`--chunked-prefill-size 8192` 限制长 prompt prefill 峰值。未启用 `--enable-torch-compile`（官方文档标注
  out of maintenance，仅利于小模型小 batch）；未默认开 FP8 KV cache（缺 scaling-factor 时 scale 默认 1.0 会掉
  精度），需要时经 `LLM_EXTRA_ARGS` 加 `--kv-cache-dtype fp8_e4m3`。
- OOM 时：经 `LLM_EXTRA_ARGS` 覆盖 `--context-length` / `--mem-fraction-static` 调小。

## 构建与运行

镜像构建在仓库根手动执行（发布由 `.github/workflows/` 管理）：

```bash
images/deployments/sglang/build.sh       # 产出 ghcr.io/curoky/devspace:llm-sglang
images/deployments/sglang/run.sh         # 在当前 GPU host 直接启动 SGLang
```

**标准运行路径由控制面 deployment 负责**：在 config 的 `deployments.llm-sglang` 声明镜像与容器块，在目标 GPU
host 的 `hosts.<host>.deployments` 里选中该引擎，再于 UI 点 Deploy（或
`POST /api/deployments/llm-sglang/hosts/<host>/deploy`）。控制面按解析后 `container` 块创建容器，形态与下述要求
一致（`unless-stopped` restart policy、host network 且监听 `127.0.0.1:<port>`）。直接登录 GPU host 时也可运行
`run.sh`；脚本创建同名并带标准 deployment labels 的容器，控制面可继续识别和清理。与 sidecar 不同处（LLM 专属，
均为新增 mount/device 例外，均在 deployment `container` 块声明）：

- 经 CDI `--device nvidia.com/gpu=all` 请求本机全部 GPU（`container.devices`）；TP8/EP8 多进程通信需要充足的
  `/dev/shm`，用 `--ipc host`（`container.ipc: host`）直接复用宿主共享内存，不再设置只作用于私有 IPC
  namespace 的 `container.shm_size`。Deployment 不继承开发默认，无需反向清除 `cap_add`/`security_opt`。
- Hugging Face cache 用 `${DEPLOYMENT_DATA}:/root/.cache/huggingface` volume 绑到托管数据根
  `~/codespace/deployments/llm-sglang`，首次启动拉取 ~172 GiB 权重到该目录，需 ≥~200 GiB 空闲空间；容器内经
  `HF_HOME=/root/.cache/huggingface` 指向它。gated/加速下载可先在 `container.environment` 或宿主注册 `HF_TOKEN`。

host 前置：NVIDIA Container Toolkit 并配好 CDI（`nvidia.com/gpu` 设备）。

## 目录

| 路径 | 职责 |
| --- | --- |
| `AGENTS.md` | 本文，SGLang 引擎契约 |
| `Dockerfile` | 基于 `debian:trixie-slim` 自装 CUDA/推理栈 + s6 + 本目录 rootfs |
| `binman.yaml` | s6/execline standalone profile + uv link |
| `rootfs/opt/llm/serve.sh` | SGLang 专用启动脚本，按环境变量拼引擎命令 |
| `rootfs/etc/s6/s6-rc.d/llm` | s6 longrun |
| `rootfs/etc/s6/s6-rc.d/user-final` | 默认 runlevel bundle，`contents.d/llm` 标记该 longrun |
| `build.sh` | 从仓库根构建本地镜像 `llm-sglang` |
| `run.sh` | 在 GPU host 直接替换并启动对应 deployment 容器 |

## 变更规则

- 与 `vllm/` 保持结构对称：一侧新增文件/knob 时评估另一侧是否需同步。
- 不烤入模型权重；不引入 Podman socket、控制面、provider token 或 repository credential。
- 新增引擎参数优先经 `serve.sh` 环境变量暴露，不写死在 s6 run 脚本；引擎命令随官方 recipe 变化时更新
  `serve.sh` 并同步本文。
- 容器运行形态（GPU/IPC、HF cache volume、网络和端口）改动必须同时更新 config 的 `deployments.llm-sglang`、
  `run.sh` 与 [`controller/AGENTS.md`](../../../controller/AGENTS.md)。
- day-0 架构支持随 Dockerfile `ARG` 演进：当前无含此架构的 tagged release，用 `SGLANG_REF`（PR ref 或未来 tag）
  锁定到含 Qwen3.8-Flash-Next 的 ref，变更时同步本文表格。
- 影响跨组件契约时同步根 [`AGENTS.md`](../../../AGENTS.md)。
