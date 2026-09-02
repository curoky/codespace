# Codespace 源码编译依赖镜像约束

本目录保存**从源码编译**的 GPU 推理/训练框架镜像资产，按项目拆成自包含子目录
[`pytorch/`](pytorch/)、[`sglang/`](sglang/)、[`vllm/`](vllm/)；本文是三子目录共用的公共契约。
与 [`images/deployments/`](../deployments/vllm/AGENTS.md) 的 serving 镜像不同：那里从预编译 wheel 装运行栈、跑
OpenAI serving；**本目录专注用本机 GPU driver 对应的 CUDA 版本从源码编译框架**，产出可直接
`import` 的可运行镜像，供开发/验证/二次分发复用。整体架构见仓库根 [`AGENTS.md`](../../AGENTS.md)。
修改本目录契约时必须同步更新本文与根 `AGENTS.md`。

## 目标与场景

- 为本机 GPU driver 支持的 CUDA 版本，从源码编译 PyTorch / SGLang / vLLM，得到与本机严格对齐的构建产物。
- 每个「CUDA 版本 × 项目版本 × 编译器 × Python」组合对应**独立一个 Dockerfile**，文件名即声明该组合。
- 首批目标硬件：8×H100（SM 9.0，Hopper），host driver 535.161.08（CUDA 12.2 配套驱动）。经 CUDA minor
  version 前向兼容可运行 cu12.9 应用；cu13 跨 major 需 driver ≥580，本机**可编译不可运行**，作前向准备。

## 命名方案（事实来源）

文件名规范（全小写、`-` 分隔维度、维度内 `.` 表版本、`.Dockerfile` 结尾）：

```
<project><主次版本>-cu<cuda>-cudnn<major>-gcc<major>-py<ver>.Dockerfile
```

`<combo>`（即去掉 `.Dockerfile` 的文件名主体）直接作为镜像 tag 后缀：
`ghcr.io/curoky/devspace:deps-<combo>`（延续 deprecated 镜像的 `deps-` 前缀）。

现有实例（H100 / gcc12 / py3.12；cu12.9 本机可运行，cu13 前向准备），六个均已本机编译验证通过：

| 项目 | 文件 | 镜像 tag |
| --- | --- | --- |
| PyTorch | `pytorch/torch2.13-cu12.9.1-cudnn9-gcc12-py3.12.Dockerfile` | `deps-torch2.13-cu12.9.1-cudnn9-gcc12-py3.12` |
| PyTorch | `pytorch/torch2.13-cu13.0.1-cudnn9-gcc12-py3.12.Dockerfile` | `deps-torch2.13-cu13.0.1-cudnn9-gcc12-py3.12` |
| SGLang | `sglang/sglang0.5.18-cu12.9.1-cudnn9-gcc12-py3.12.Dockerfile` | `deps-sglang0.5.18-cu12.9.1-cudnn9-gcc12-py3.12` |
| SGLang | `sglang/sglang0.5.18-cu13.0.1-cudnn9-gcc12-py3.12.Dockerfile` | `deps-sglang0.5.18-cu13.0.1-cudnn9-gcc12-py3.12` |
| vLLM | `vllm/vllm0.28-cu12.9.1-cudnn9-gcc12-py3.12.Dockerfile` | `deps-vllm0.28-cu12.9.1-cudnn9-gcc12-py3.12` |
| vLLM | `vllm/vllm0.28-cu13.0.1-cudnn9-gcc12-py3.12.Dockerfile` | `deps-vllm0.28-cu13.0.1-cudnn9-gcc12-py3.12` |

各维度定案依据：

| 维度 | 取值 | 依据 |
| --- | --- | --- |
| CUDA | `cu12.9.1` / `cu13.0.1` | cu12.9：本机 driver 535 经 CUDA 12 minor 前向兼容可跑，是当前可运行目标。cu13.0.1：跨 major，需 driver ≥580，本机只可编译不可运行，为升级 driver 后前向准备。 |
| 编译器 | `gcc12` | 三项目共同交集：cu12.9/cu13 nvcc host compiler 均支持，且三项目源码都要求 gcc≥11.3（PyTorch C++20 头文件不兼容 <11.3）。Ubuntu 24.04 默认 gcc-13，显式装 gcc-12 并 `update-alternatives` 设默认。 |
| Python | `py3.12` | GPU 推理/编译栈生态兼容的最新版本（3.13 部分构建链未就绪），与 `images/deployments/` 一致。 |
| torch | `torch 2.13.0` / `torchvision 0.28.0` / `torchaudio 2.11.0` | 三项目最新稳定版共同 pin torch 2.13.0。**torchaudio 版本线独立于 torch**：不存在 torchaudio 2.13.0，与 torch 2.13.0 配对的最新 tag 是 2.11.0；torchvision 对应 0.28.0。cu129/cu130 wheel 索引均有这三者。 |

## 组装约定

三子目录结构对称，Dockerfile 遵循统一 **两 stage** 套路：

1. **builder stage**：`FROM nvidia/cuda:<cuda>-cudnn-devel-ubuntu24.04 AS builder`，提供 nvcc + cuDNN +
   头文件，glibc 与 nvcc 匹配。**在此 stage 内**装 gcc-12、binman(`uv`)，`uv venv --python 3.12` 建
   `/opt/deps/venv`，`git clone` 项目 release tag（`ARG <PROJECT>_REF` pin），设编译 env 后从源码编译装入 venv。
   **必须在 builder stage 内编译**：直接在 debian:trixie final stage 内跑 nvcc 会触发 glibc 与 CUDA 头文件的
   cospi/sinpi noexcept 冲突，故在 Ubuntu 24.04 devel 内编译再 COPY 产物。
2. **final stage**：`FROM docker.io/debian:trixie-slim`，apt 只装运行期依赖（`ca-certificates`、`libgomp1`），
   `COPY --from=builder` 拷入瘦身后的 CUDA toolkit 与 `/opt/deps/venv`（vLLM 还需 `COPY` 源码树因其 editable 装）。
3. 产物为可运行镜像：`ENTRYPOINT` 缺省进 venv 的 python（无 s6、无 serve.sh，非 serving 镜像）。

各项目源码编译差异：

- **PyTorch**：三件套（torch/torchvision/torchaudio）全部 `git clone --branch` 后
  `uv pip install --no-build-isolation` 源码编译。`TORCH_CUDA_ARCH_LIST=9.0`（torch 构建系统内部自动展开
  sm_90a，走安全路径）。
- **vLLM**：主包 `-e . --no-build-isolation` 源码编译 CUDA kernel（读已装 torch 的 CUDA 配置，故先按 CUDA_TAG
  装 torch 三件套 wheel）。因 `--no-build-isolation`，编译前须预装构建后端依赖
  `setuptools wheel setuptools-scm setuptools_rust cmake<4 ninja packaging`（否则报 `No module named
  'setuptools_rust'`）。
- **SGLang**：主包 `python/` 目录 `-e` editable 装（走构建隔离自动拉构建依赖）；GPU kernel
  （sglang-kernel / sgl-deep-gemm）与 torch 三件套从官方索引装**预编译 wheel**——整栈源码编译 CUDA kernel 成本
  极高，主包源码编译已满足目标。cu12.9 版本额外清理 sglang 依赖默认拉入的 cu13 冗余 nvidia wheel、回装 cu12 对齐包。

## H100（SM 9.0a）定制优化

针对本机 Hopper 架构做 arch 级定制：

- **vLLM / SGLang** 用 `TORCH_CUDA_ARCH_LIST=9.0a`：`9.0a` 变体启用 Hopper 专属 wgmma/TMA 指令，vLLM 的 FP8 与
  cutlass kernel、SGLang 的 FA3 kernel 依赖之；只编本机架构缩短构建时间、减小体积。
- **PyTorch** 保持 `9.0`：torch 构建系统会自动为 sm_90 展开 `sm_90a`，无需手动加 `a`。

## 编译资源约束

- 构建**实际在远端 rootful podman host 上执行**（192 核 / 317GB RAM），本瘦客户端容器的内存限制不影响它，故默认
  高并发：`ARG MAX_JOBS=48`、`NVCC_THREADS=4`（`CMAKE_BUILD_PARALLEL_LEVEL` 随 `MAX_JOBS`）。torch 全量编译
  在此并发下约 17 分钟（保守限并发时曾达 160 分钟）。
- `MAX_JOBS`/`NVCC_THREADS` 由 `build.sh` 以 `--build-arg` 传入，可用同名环境变量覆盖；内存受限的 host 调小即可，
  不必改 Dockerfile 默认。SGLang 装 wheel 不编译 kernel，其 Dockerfile 不消费这两个 arg（构建时的
  `build args were not consumed` warning 属正常）。

## 瘦身策略（保守，起步不激进）

起步只做低风险裁剪，避免误删构建/运行必需项：

- **builder stage 在 COPY 前**删除静态库 `*.a`（占 devel toolkit 约一半体积、动态链接场景用不到）、
  `doc`/`share`/`src`/`extras`/`compute-sanitizer`/`compat` 等编译期不需要的目录（在 stage 内删，删后 COPY
  才真正缩小镜像；COPY 后删只会加白障层）。
- **final stage** 清 apt 缓存（`rm -rf /var/lib/apt/lists/*`）、清 `uv`/pip 缓存与 build 临时目录。
- 保留 nvcc、cuDNN、头文件与运行期共享库；**不**做剥离 symbol、拆分运行时/编译时等激进裁剪（后续按需再加）。

## 构建与运行

本机为 podman-in-podman 环境，`docker` CLI 即 podman，可直接本机构建。各子目录一个 `build.sh`，从仓库根执行；
`build.sh` 接受可选的 combo 名作为 `$1` 以构建其他变体（缺省构建 cu12.9 组合）：

```bash
images/deps/pytorch/build.sh                                          # cu12.9（缺省）
images/deps/pytorch/build.sh torch2.13-cu13.0.1-cudnn9-gcc12-py3.12   # cu13 变体
images/deps/sglang/build.sh                                           # cu12.9
images/deps/sglang/build.sh sglang0.5.18-cu13.0.1-cudnn9-gcc12-py3.12 # cu13 变体
images/deps/vllm/build.sh                                             # cu12.9
images/deps/vllm/build.sh vllm0.28-cu13.0.1-cudnn9-gcc12-py3.12       # cu13 变体

# 覆盖并发（如内存受限的 host）：
MAX_JOBS=8 NVCC_THREADS=2 images/deps/vllm/build.sh
```

cu13 组合构建前需先拉 base 镜像 `nvidia/cuda:13.0.1-cudnn-devel-ubuntu24.04`（~11GB）。运行需 host NVIDIA
Container Toolkit 提供 driver（`--device nvidia.com/gpu=all`）；cu12.9 镜像本机 driver 535 即可跑，cu13 镜像
需 driver ≥580。镜像自带 CUDA runtime 与 nvcc toolkit，容器内 `import torch` 即可用 GPU。

## 目录

三子目录结构对称，下表以 `<project>` 指代 `pytorch`/`sglang`/`vllm`：

| 路径 | 职责 |
| --- | --- |
| `AGENTS.md` | 本文，三项目共用公共契约与命名方案 |
| `<project>/<combo>.Dockerfile` | 该「CUDA×版本×编译器×Python」组合的源码编译 Dockerfile |
| `<project>/build.sh` | 从仓库根构建该项目镜像，接受 combo 名 `$1` 切换变体 |
| `<project>/binman.yaml` | binman 清单，link `uv` 到 `/opt/bm` |

## 变更规则

- 新增组合：按命名方案加一个 `<combo>.Dockerfile`，不复用/覆盖已有组合文件；`build.sh` 已参数化，传 combo 名即可。
- CUDA/编译器/Python/项目版本任一维度变化都要体现在**文件名**与镜像 tag 上，保持文件名即组合声明的不变量。
- 三子目录保持结构对称：一侧调整 stage 结构、瘦身或编译 env 时评估另两侧是否同步。
- 必须在 builder(Ubuntu CUDA devel) stage 内编译，不得移到 debian final stage（glibc/nvcc 头文件冲突）。
- vLLM `--no-build-isolation` 编译前的构建后端依赖预装不得移除（尤其 `setuptools_rust`）。
- 影响跨组件契约时同步根 [`AGENTS.md`](../../AGENTS.md)。
