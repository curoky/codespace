# Codespace LLM Serving 约束

本目录保存 host 级 **Qwen3.8-Flash-Next-FP8** 推理 serving 镜像资产，按引擎拆成两个自包含子目录
[`vllm/`](vllm/) 与 [`sglang/`](sglang/)；本文是两子目录共用的公共契约。镜像管理方案基本对齐
[`images/sidecar/`](../sidecar/AGENTS.md)：以自建 s6 init 为 PID 1，服务定义放在各子目录的
`rootfs/etc/s6/s6-rc.d/`，OpenAI 兼容 API 只经 host loopback 暴露。整体架构见仓库根
[`AGENTS.md`](../../AGENTS.md)。修改本目录契约时必须同步更新本文与根 `AGENTS.md`。

模型事实：Qwen3.8-Flash-Next-FP8 是 2026-08-26 开源的多模态 MoE（125B 主模型 + 51B N-gram embedding，
单 token 激活约 6B），原生上下文 262,144，可 YaRN 扩到 1,000,000。FP8 权重约 172.78 GiB。

## 不变量

- 每个 host 最多一个 LLM serving container，固定名 `codespace-llm`，identity 只由 host 决定，不含
  project/instance ID。不进 project 生命周期，不参与 `codespace.managed=true` 的 environment inventory。
- 单容器只跑单一引擎，即单主推理进程；无 project workspace、SSH 服务、deploy key、repository 或 SSH 投影。
- API 只经 host loopback 暴露：bridge network 且仅向 `127.0.0.1:<port>`（默认 8003，避开 sidecar 的 8002）
  publish 端口。
- **模型权重不烤进镜像**：~172 GiB FP8 权重经 bind-mount 的 Hugging Face cache 在首次启动时由引擎拉取。
- 镜像不含 Podman socket、控制面、provider token 或 repository credential。

## 引擎与镜像

vLLM 与 SGLang 都被官方列为 day-0 引擎，各自一个独立子目录、一套完整镜像资产（Dockerfile / binman.yaml /
rootfs / build.sh / run.sh），互不共享文件。base image 对齐 sidecar，统一用 `docker.io/debian:trixie-slim`；
与 sidecar 不同，本镜像需**自装完整 CUDA + 推理栈**（Debian 无 CUDA runtime 与推理引擎）：

| 引擎 | 子目录 | 镜像 tag | 推理栈 | s6 longrun |
| --- | --- | --- | --- | --- |
| vLLM | `vllm/` | `ghcr.io/curoky/devspace:llm-vllm` | uv venv `vllm==${VLLM_VERSION}`（默认 `0.23.0`，`--torch-backend`） | `llm` |
| SGLang | `sglang/` | `ghcr.io/curoky/devspace:llm-sglang` | uv venv 从 PR 源码装（`${SGLANG_REF}` 默认 `pull/36497/head`，cu129 kernel） | `llm` |

两子目录内部结构完全对称，仅推理栈与引擎命令不同；s6 longrun 在各自子目录内统一命名 `llm`（因为一个镜像只
含一个引擎，无需区分）。组装顺序对齐 sidecar：Debian slim → apt 基础包（含 `python3`）→ binman 装
standalone s6/execline 与 uv → uv 建 venv 装推理栈 → `COPY <engine>/rootfs/` → `setup-s6.sh` → s6 init。
推理栈装进独立 venv `/opt/llm/venv`（`LLM_VENV`），`serve.sh` 显式用该 venv 的二进制（s6 生成的 init PATH
不含 venv）。venv 用 Python 3.12——这是 GPU 推理栈生态兼容的最新版本：vLLM 名义支持 3.10–3.13，但 SGLang
的 GPU wheel 与 flashinfer/xformers 等关键依赖的预编译 wheel 目前只稳定覆盖到 3.12，改 3.13 会构建失败。
CUDA userspace 由 host 的 NVIDIA Container Toolkit 在运行期提供，推理 wheel 自带其余 CUDA runtime 库。

**CUDA 版本（默认 cu129）**：vLLM/SGLang 的默认 PyPI wheel 现已升到 CUDA 13（需 host 驱动 ≥580），但目标 8×H100 节点跑 driver 535 / CUDA 12.2，故两镜像默认按 CUDA 12.9 装：vLLM 用 uv `--torch-backend=cu129`（`ARG TORCH_BACKEND`，固定值而非 `auto`，因为 CI builder 无 GPU 驱动可探测）；SGLang 走官方 cu129 recipe（对齐 docs.sglang.io 安装文档与上游 `docker/Dockerfile` 的 torch_deps 序列）——从 PR 源码装 `sglang` 后，依次从 cu129 index force-reinstall **pinned torch 三件套**（`ARG TORCH_SPEC`，默认 `torch==2.13.0 torchvision==0.28.0 torchaudio==2.11.0`；裸 `torch` 会拉到 cu13 默认版）、`sglang-kernel`（pip 名，cu129 wheel 内部为 `sglang_kernel`）与 `sgl-deep-gemm`（`--no-deps`），`ARG CUDA_TAG` 选 index。CUDA 13 host 用 `TORCH_BACKEND=cu130` / `CUDA_TAG=cu130` + `TORCH_SPEC="torch torchvision torchaudio"` 覆盖。SGLang 不装 `[all]` extra，改用官方 recipe 的独立 kernel 包。

**day-0 架构（Qwen3.8-Flash-Next 尚无 SGLang release）**：SGLang 目前**没有任何含此架构的 tagged release**，PyPI 装不到；按官方 cookbook，模型支持在 PR [#36497](https://github.com/sgl-project/sglang/pull/36497)，故 SGLang 镜像不 pin `SGLANG_VERSION`，改用 `ARG SGLANG_REF`（默认 `pull/36497/head`）从源码 clone 该 PR 后 `uv pip install -e python`（Dockerfile 因此新增 apt `git`）。该源码树用 setuptools-rust 内嵌 3 个 PyO3 crate（`sglang-grpc`/`sglang-mm`/`sglang-server`），editable 装会调 `cargo`；slim 镜像无 Rust 工具链，故 `ARG SGLANG_BUILD_RUST_EXTS=none` 跳过——它们只支撑 gRPC/multimodal/model-gateway 入口，`sglang.launch_server`（OpenAI HTTP）不依赖。需要这些入口时设 `all` 并自备 cargo。待架构进入 release，把 `SGLANG_REF` 指向该 tag 并可回退到 `uv pip install sglang`。vLLM 侧仍以 `VLLM_VERSION`（默认 `0.23.0`）演进；若该稳定版尚未含此架构，提升到含该架构的版本（官方 recipe 用专用 tag 或 nightly），启动报 unknown-architecture 时提升版本。AMD GPU 不用本 CUDA 镜像，改用官方 ROCm 镜像。

## s6 init

对齐 sidecar：`images/dev/script/setup-s6.sh` 从 `/opt/bm/store` 的 s6/execline 二进制编译 `/etc/s6/db`
并生成 `/etc/s6/init`，默认 runlevel `user-final`。每个镜像的 `user-final` bundle 只含本引擎的一个 longrun
`llm`。execline run 脚本用 `s6-envdir -Lf -- /run/s6/container_environment` 读容器环境
（含 `LLM_MODEL`/`LLM_HOST`/`LLM_PORT`/`LLM_EXTRA_ARGS`）后 `exec /opt/llm/serve.sh`；日志写 `/var/log/llm.log`。

每个子目录的 `serve.sh` 是该引擎专用启动脚本（不再有引擎 switch），按环境变量拼命令并 `exec` 引擎：

| 环境变量 | 默认 | 说明 |
| --- | --- | --- |
| `LLM_MODEL` | `Qwen/Qwen3.8-Flash-Next-FP8` | 模型 id 或本地路径（两引擎） |
| `LLM_HOST` | `0.0.0.0` | 容器内监听地址（bridge 需 0.0.0.0 才能被 publish 转发，两引擎） |
| `LLM_PORT` | `8003` | 容器内 OpenAI API 端口（两引擎） |
| `LLM_EXTRA_ARGS` | 空 | 追加到引擎命令的额外参数（两引擎） |

两引擎的优化参数均已按实测 8×H100 80GB 拓扑写死在各自 `serve.sh` 里（不再配置化），只保留
model/host/port/extra 四个部署相关 env，需临时改参用 `LLM_EXTRA_ARGS` 覆盖。写死项：
- vLLM：TEP8（`--tensor-parallel-size 8 --enable-expert-parallel`）、`--max-model-len 262144`、
  `--gpu-memory-utilization 0.90`、`--enable-prefix-caching`、分块 prefill
  （`--enable-chunked-prefill --max-num-batched-tokens 8192`）、`--max-num-seqs 256`。
- SGLang：TEP8（`--tp-size 8 --ep-size 8`）、`--context-length 262144`、`--mem-fraction-static 0.85`、
  `--chunked-prefill-size 8192`、`--max-running-requests 96`、GDN+QSA 必需的
  `--linear-attn-*-backend flashinfer` + `--mamba-ssm-dtype bfloat16`、in-checkpoint MTP head 的 NEXTN
  speculative decoding。

两引擎均开启 `--reasoning-parser qwen3` 与 `--tool-call-parser qwen3_coder`。

## 硬件与拓扑（单机 8×H100）

- 实测拓扑（`nvidia-smi`）：8×H100 80GB HBM3、compute cap 9.0（Hopper，原生 FP8 e4m3）、全互联 NVLink
  （NV18 / NVSwitch，~900 GB/s）、双 NUMA（GPU0-3→node0，GPU4-7→node1）。8×80 GB = 640 GB，FP8 权重
  ~172.78 GiB 放得下，KV/state cache 有余量但比 cookbook 的 H200 141GB 紧。
- **8×H100 的 FP8 必须用 TEP8（TP8 + Expert Parallel），不能用普通 TP8**（512 专家 MoE 布局要求）。
  vLLM 以 `--enable-expert-parallel` 开启，SGLang 以 `--ep-size` 开启，两 `serve.sh` 默认即为 TEP8。
- 全 NVLink mesh 下 TP8 all-reduce 廉价：无需 `--enable-p2p-check`，custom all-reduce 保持默认开。
- SGLang serve.sh 针对 80 GB 写死了适配参数：`--mem-fraction-static 0.85` 给 Mamba/GDN state cache 与
  activation 留余量、`--chunked-prefill-size 8192` 限制长 prompt prefill 峰值。未启用 `--enable-torch-compile`
  （官方文档标注 out of maintenance，仅利于小模型小 batch）；未默认开 FP8 KV cache（缺 scaling-factor
  时 scale 默认 1.0 会掉精度），需要时经 `LLM_EXTRA_ARGS` 加 `--kv-cache-dtype fp8_e4m3`。
- OOM 时：SGLang 经 `LLM_EXTRA_ARGS` 覆盖 `--context-length` / `--mem-fraction-static` 调小；vLLM 降
  `MAX_MODEL_LEN`/`GPU_MEM_UTIL`，或设 `VLLM_PLE_CPU_OFFLOAD=1` 把 51B N-gram 表卸到主机内存（需大内存 host）。

## 构建与运行

在仓库根手动构建与运行（发布由 `.github/workflows/` 管理），各引擎脚本在自己子目录：

```bash
images/llm/vllm/build.sh         # 产出 ghcr.io/curoky/devspace:llm-vllm
images/llm/vllm/run.sh
images/llm/sglang/build.sh       # 产出 ghcr.io/curoky/devspace:llm-sglang
images/llm/sglang/run.sh
```

`run.sh` 对齐 sidecar 启动器形态：替换固定名 `codespace-llm` 容器、`unless-stopped` restart policy、
bridge network 且只 publish 到 `127.0.0.1:<port>`。与 sidecar 不同处（LLM 专属，均为新增 mount/device 例外）：

- 经 CDI `--device nvidia.com/gpu=all` 请求本机全部 GPU；`--ipc host`、`--shm-size 32g`。
- bind-mount 宿主 Hugging Face cache（`HF_HOME`，默认 `~/.cache/huggingface`）到容器 `/root/.cache/huggingface`，
  首次启动拉取 ~172 GiB 权重到该目录，需 ≥~200 GiB 空闲空间。gated/加速下载可先 `export HF_TOKEN`。

host 前置：NVIDIA Container Toolkit 并配好 CDI（`nvidia.com/gpu` 设备）。

## 目录

两子目录结构对称，下表以 `<engine>` 指代 `vllm` 或 `sglang`：

| 路径 | 职责 |
| --- | --- |
| `AGENTS.md` | 本文，两引擎共用公共契约 |
| `<engine>/Dockerfile` | 基于 `debian:trixie-slim` 自装 CUDA/推理栈 + s6 + 本子目录 rootfs |
| `<engine>/binman.yaml` | s6/execline standalone profile + uv link |
| `<engine>/rootfs/opt/llm/serve.sh` | 该引擎专用启动脚本，按环境变量拼引擎命令 |
| `<engine>/rootfs/etc/s6/s6-rc.d/llm` | 该引擎 s6 longrun |
| `<engine>/rootfs/etc/s6/s6-rc.d/user-final` | 默认 runlevel bundle，`contents.d/llm` 标记该 longrun |
| `<engine>/build.sh` | 从仓库根构建本地镜像 `llm-<engine>` |
| `<engine>/run.sh` | 替换固定名 `codespace-llm` 单例，挂载 GPU/HF cache 并 loopback publish |

## 变更规则

- 两子目录保持结构对称：一侧新增文件/knob 时评估另一侧是否需同步。
- 不烤入模型权重；不引入 Podman socket、控制面、provider token 或 repository credential。
- 新增引擎参数优先经 `serve.sh` 环境变量暴露，不写死在 s6 run 脚本；引擎命令随官方 recipe 变化时更新对应
  子目录的 `serve.sh` 并同步本文。
- day-0 架构支持随各 Dockerfile `ARG` 演进：vLLM 用 `VLLM_VERSION`，SGLang 因尚无 release 用 `SGLANG_REF`
  （PR ref 或未来 tag）；锁定到含 Qwen3.8-Flash-Next 的版本/ref，变更时同步本文表格。
- 影响跨组件契约时同步根 [`AGENTS.md`](../../AGENTS.md)。
