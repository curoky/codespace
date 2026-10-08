# ASR Maintenance

本目录是普通话完整录音转写服务，产品边界、模型分工与执行流程见 [DESIGN.md](DESIGN.md)。
本文件供 agents 维护实现；模型特有参数的原因、协议限制和坑写在代码旁，不再建每模型
说明文件。版本、端口和 snapshot 的实际值以代码与锁文件为准。

## Model Storage Footprint

下表是当前模型、Serving、依赖栈与存储信息的统一维护入口。全部环境使用 Python 3.12.14；
框架、Torch 和 Transformers 版本来自各目录 `uv.lock` 的 Linux 解析结果。CUDA 是 toolkit
release；CPU-only 环境记为 `—`。大小统一使用二进制 GiB（`1 GiB = 1,073,741,824 bytes =
1024³ bytes`）。

| 模型 / checkpoint | Serving 接口 | SDK / 版本 | Transformers 版本 | vLLM 版本 | Torch 版本 | CUDA 版本 | 参数大小（GiB） | 权重交付 | `.venv` 逻辑大小（GiB） | SGLang 依据 |
| --- | --- | --- | --- | --- | --- | --- | ---: | --- | --- | --- |
| [`firered-llm`](https://huggingface.co/allendou/FireRedASR2-LLM-vllm) | transcription（[作者配方][firered]） | — | 5.17.0 | 0.31.0 | 2.13.0 | 13.0.3 | 31.147 | ❌ | 7.392 | 未找到原生依据 |
| [`firered-punc`](https://huggingface.co/FireRedTeam/FireRedPunc) | 本模型 HTTP | [FireRedASR2S][firered] 0.0.1 @ `4e7d9aa` / CPU | 5.1.0 | — | 2.10.0+cpu | — | 0.762 | ✅ | 0.832 | 未找到原生依据 |
| [`firered-vad`](https://huggingface.co/FireRedTeam/FireRedVAD) | 本模型 HTTP | [FireRedASR2S][firered] 0.0.1 @ `4e7d9aa` / CPU | 5.1.0 | — | 2.10.0+cpu | — | 0.002 | ✅ | 0.832 | 未找到原生依据 |
| [`moss-audio`](https://huggingface.co/OpenMOSS-Team/MOSS-Audio-8B-Instruct) | audio chat（[作者文档][moss-audio]） | — | 5.17.0 | 0.31.0 | 2.13.0 | 13.0.3 | 16.862 | ❌ | 7.392 | 作者 fork |
| [`moss-td`](https://huggingface.co/OpenMOSS-Team/MOSS-Transcribe-Diarize) | transcription（[作者文档][moss-td]） | — | 5.17.0 | 0.31.0 | 2.13.0 | 13.0.3 | 1.692 | ✅ | 7.396 | Omni 原生；主仓库未找到依据 |
| [`nemotron-diarization`](https://huggingface.co/nvidia/Nemotron-3-Diarization) | 本模型 HTTP | NeMo 3.1.0+ca3f93a51 | 4.57.6 | — | 2.13.0 | 13.0.3 | 0.185 | ✅ | 5.288 | 未找到原生依据 |
| [`paraformer`](https://huggingface.co/funasr/paraformer-zh) | 本模型 HTTP | [FunASR][funasr] 1.4.16 | 4.57.6 | — | 2.13.0 | 13.0.3 | 0.820 | ✅ | 4.973 | 未找到原生依据 |
| [`pyannote-community-1`](https://huggingface.co/pyannote/speaker-diarization-community-1) | 本模型 HTTP | [pyannote.audio][pyannote] 4.0.7 | — | — | 2.13.0 | 13.0.3 | 0.031 | ✅ | 4.819 | 未找到原生依据 |
| [`qwen3-aligner`](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B) | pooling + 本模型 HTTP（[Qwen SDK][qwen]） | — | 5.17.0 | 0.31.0 | 2.13.0 | 13.0.3 | 1.709 | ✅ | 7.396 | 未找到等价原生接口 |
| [`qwen3-asr-1.7b`](https://huggingface.co/Qwen/Qwen3-ASR-1.7B) | transcription（[Qwen SDK][qwen]） | — | 5.17.0 | 0.31.0 | 2.13.0 | 13.0.3 | 4.376 | ❌ | 7.392 | 主仓库 / Omni 原生 |
| [`sensevoice`](https://huggingface.co/FunAudioLLM/SenseVoiceSmall) | 本模型 HTTP | [FunASR][sensevoice] 1.4.16 | 4.57.6 | — | 2.13.0 | 13.0.3 | 0.872 | ✅ | 4.973 | 未找到原生依据 |
| [`vibevoice`](https://huggingface.co/microsoft/VibeVoice-ASR-HF) | audio chat（[作者文档][vibevoice]） | — | 5.17.0 | 0.31.0 | 2.13.0 | 13.0.3 | 15.517 | ❌ | 7.392 | 未找到原生依据 |
| [`whisper-large-v3`](https://huggingface.co/openai/whisper-large-v3) | transcription（[模型来源][whisper]） | — | 5.17.0 | 0.31.0 | 2.13.0 | 13.0.3 | 2.875 | ❌ | 7.392 | 主仓库原生 ASR |

参数大小按各 `download_model.sh` 固定 revision 的仓库 metadata 统计，只计算 checkpoint /
weight 文件，不包含 config、tokenizer、词典、CMVN 或 download cache；`.nemo`、`.pth.tar`
等不可拆分 checkpoint 按整个文件计算。`.venv` 是对每个目录独立执行
`du --apparent-size --block-size=1 --summarize` 得到的逻辑大小；共享 hardlink 会在每行
完整计数，不能将各行相加作为 image 物理占用。`✅` 表示 image 内置，`❌` 表示 runtime
下载。

参数文件总计 76.850 GiB，其中 image 内置 6.074 GiB，runtime 下载 70.776 GiB。计入
allowlist 中的必要配置与 tokenizer 后，实际内置下载约 6.101 GiB，实际 runtime 下载约
70.811 GiB。13 个 `.venv` 的逻辑大小合计 73.488 GiB；同一 layer 内完成 uv cache 与内容
hardlink 去重后的整体实际分配为 9.520 GiB，不能稳定归属到单个模型。全局 CUDA compiler
toolkit 在既有 compat libraries 之外增加约 0.352 GiB。修改 revision、allowlist、Python、lock
或 toolkit payload 时重新构建镜像并同步更新本表。

环境安装完成后还会按文件内容对全部模型与 server 环境做第二遍去重；它只忽略 mtime，
mode、owner 与 xattr 不同的文件不会合并。上面的整体实际分配已计入 server `.venv`。

Serving 与 SGLang 结论是 2026-10-07 的上游核对记录，依据 [vLLM 0.31.0][vllm-models]、
[SGLang 0.5.21][sg-models] 和 [SGLang-Omni 0.1.7][omni]，不代替当前 Host 的真实推理验证。
升级时重新核对实际 model class、endpoint 和 response schema；SGLang 主仓库、Omni 与作者
fork 是不同 runtime，OpenAI-compatible HTTP 不等于模型原生支持。Qwen 普通 / `-hf`、
VibeVoice 原版 / HF、FireRed 原始 / 转换权重不能互换；FunASR 的 `paraformer-zh` 简称在不同
hub 映射不同，始终以下载脚本的完整 repo 为准。

## Context And Ownership

| 修改内容 | Source of truth / 先读 |
| --- | --- |
| 模型启动、参数、环境 | `models/<model>/run`；SDK 参数在同目录 `service.py` |
| 权重来源与格式 | `models/<model>/download_model.sh` 的 repo、revision、include |
| image 内置权重集合 | `install-bundled-model-weights.sh`；对应模型不保留 s6 download service |
| Python / 依赖版本 | 每目录 `.python-version`、`pyproject.toml`、`uv.lock` |
| 模型地址与请求协议 | `models/<model>/client.py` 的 `URL`、`infer(http, request)` |
| 能力与资源预算 | `models/catalog.py`；不在这里放启动 flags 或端口 |
| 原子请求、转录流程、产物 | [server/AGENTS.md](server/AGENTS.md) |
| GPU、s6 启停和进程退出 | [ops/AGENTS.md](ops/AGENTS.md) |
| image / 用户 / 日志 / 服务依赖 | `Dockerfile`、`rootfs/`；遵循上层 Service runtime 约定 |

只维护五方案用到的模型，不增加通用 worker、参数 launcher、环境准备 job 或动态生成
s6 文件的工具。配置文件使用 YAML，uv 工具文件除外。参数、export 一行一个，逻辑段落
留空行。参数解释贴近实现，仅写约束或理由，不复述命令。

个人使用，一份录音对应一次 HTTP 请求，处理完直接返回 zip。CLI 控制文件并发；
不引入持久任务队列、任务状态、轮询、幂等键、恢复、部署指纹或跨请求缓存。模型驻留
与 GPU 分配保留必要的进程内状态。复杂度主要用于文字、时间戳和 speaker 的质量约束。

## Model Contract

- `install-model-environments.sh` 在 image build 的同一个 layer 中遍历全部模型并使用
  `UV_LINK_MODE=hardlink` 创建独立 `.venv`；server 安装完成后再对所有环境做 content-based
  hardlink，补齐 uv cache artifact 之外的相同文件。CUDA toolkit meta package、compiler、
  CRT 与 NVVM 由 image 全局提供，安装时跳过 vLLM kernel package 间接声明的对应 wheel。
  任一 lock 失配、安装或去重失败必须使 build 失败。
- `run` 与 `download_model.sh` 使用 `uv run --frozen --no-sync`，只运行 image 内预装环境，
  不在启动或下载权重时解析、安装或更新依赖。
- 权重固定在本目录 `weights/`。下载脚本只调用 HF CLI；`run` 只加载本地权重，不代替下载。
  下载脚本用显式 include 只取 serving 所需的权重格式、配置、processor 与自定义模型代码，
  不下载同一 checkpoint 的其他框架或精度副本。HF 根据 local-dir metadata 复用文件。
  内置模型在 build 中下载且不保留 runtime download service；其余模型仍在首次启动时下载。
  改变 revision 时先停止 runtime 下载模型并清理旧 weights，避免旧文件混入；本地 `.venv`
  与权重不进入 build context，image 中的环境与内置权重只由锁文件和固定 snapshot 构建。
- 监听地址和端口在 `run` 显式固定，client 的 `URL` 同步维护。调度器从 client 读取地址
  做 readiness，不生成端口，也不把地址注入模型。改变端口时同步 DESIGN 的服务表。
- vLLM transcription 的 `SpeechToTextConfig` 由各 model class 从 processor 构造，`run`
  不传 server 级覆盖参数。普通 ASR 由上层保持不超过 30 秒，catalog 记录相同模型预算；
  联合模型根据 catalog 的上限切窗。升级 vLLM 时核对模型实现与 CLI parser，不能只依据
  旧启动参数。
- SDK 服务只接收 `/data/asr` 内真实文件；原生 vLLM client 发送音频内容。数据目录是镜像
  内固定契约，改变 Host 存储位置用 bind mount；不要只改 server 的路径而破坏 SDK 访问。
- 模型不读取应用配置环境变量。GPU 服务的唯一动态输入是 `CUDA_VISIBLE_DEVICES`：由
  ops 分配、s6 传入。不要 hardcode 物理卡号；SDK 的 `cuda:0` 表示本进程可见的第一张卡。
  CPU 服务无需这项输入。
- `run` 固定 offline、线程预算等必要环境；vLLM 的 `CUDA_HOME` 指向 image 全局
  `/usr/local/cuda-13.0`，其 `bin` 由 image 加入 `PATH`，供 FlashInfer runtime JIT 使用。
  toolkit 从固定 digest 的 NVIDIA CUDA devel image 取 compiler、headers、NVVM、CUDA runtime
  linker inputs 与 driver stub，不从模型 venv 选择 compiler；FlashInfer 的 NVRTC 与 GPU runtime
  libraries 仍由 venv 的锁定依赖提供。vLLM 的 `LD_LIBRARY_PATH` 固定为 image 内 CUDA compat
  和 toolkit `lib64` 目录，不含仅供链接的 driver stub。不要拼接 Host 的库路径、代理或 uv /
  HF 环境变量。
- 模型间不共用 `.venv`。SDK 的 Torch / torchaudio 必须成套；不要为了统一版本而与 vLLM
  混装。修改 TP、精度、显存利用率或上下文预算后同步 catalog 的资源 / 时长限制。
  显存利用率是独占设备上的预算，不是模型精确需求。
- Runtime HF token 使用 x 默认的 `/home/x/.cache/huggingface/token`，只读挂载且 x 可读。
  Image build 通过 `huggingface_token` secret mount 提供 token；pyannote 需预先接受模型访问
  条件，GitHub Actions 对应 repository secret 是 `HUGGINGFACE_TOKEN`。token 不写入脚本、
  命令行、build argument 或 image layer。

## Image And S6

镜像继承 `service-s6`，在构建时安装系统工具、Python、server、全部模型环境与选定小模型
权重，并编译静态 graph。全部环境必须在同一 `RUN`、同一 filesystem 中创建，先依靠 uv
cache hardlink 去重，再用 util-linux `hardlink` 比较内容并合并剩余副本；后一步保留 mode、
owner 和 xattr，只忽略 mtime，并优先复用 link count 最高的 inode。Python、环境与内置权重
安装使用 Dockerfile 的 `USER x`，cache 在对应 `RUN` 结束前删除；s6 graph 切回 root 编译。
其余大模型权重仍在运行时准备。uv 的 Python、HF 的 cache / token 使用 x 默认目录，不转发
工具或代理环境变量。

| 资产 | 维护约定 |
| --- | --- |
| `rootfs/etc/s6/s6-rc.d/asr-<model>-download/` | 仅 runtime 下载模型拥有；oneshot 以 x 调本模型下载脚本 |
| `rootfs/etc/s6/s6-rc.d/asr-<model>/` | longrun；runtime 下载模型依赖 download，内置模型直接启动 |
| `rootfs/etc/s6/s6-rc.d/asr-server/` | 以 x 调 `server/run`；server 环境已在构建时安装，使用 `--no-sync` |
| `install-model-environments.sh` | build-only；顺序安装全部锁定模型环境并强制 uv cache hardlink，失败立即终止 |
| `install-bundled-model-weights.sh` | build-only；固定内置模型集合并清除 local-dir metadata |
| `rootfs/usr/local/bin/asr-model-service` | root-owned 受限启停入口，由 sudoers 仅授权 x 调用 |
| `/var/log/s6.asr-*.log` | `redirfd -w` + `fdmove`，沿用 Workspace 日志范式 |
| `/data/asr` | 请求临时音频，Host mount 必须允许 x 写入；正常结束与异常返回均清理 |

### Runtime Mounts

容器替换后复用 runtime 下载的模型参数时，控制面必须为以下目录分别提供可写 bind mount：

```yaml
volumes:
  - ${RESOURCE_DATA}/models/firered-llm:/opt/asr/models/firered-llm/weights
  - ${RESOURCE_DATA}/models/moss-audio:/opt/asr/models/moss-audio/weights
  - ${RESOURCE_DATA}/models/qwen3-asr-1.7b:/opt/asr/models/qwen3-asr-1.7b/weights
  - ${RESOURCE_DATA}/models/vibevoice:/opt/asr/models/vibevoice/weights
  - ${RESOURCE_DATA}/models/whisper-large-v3:/opt/asr/models/whisper-large-v3/weights
```

这些 Host 目录可以初始为空，首次启动的 download oneshot 会写入固定 snapshot；目录及已有
文件必须允许容器用户 x（UID/GID `5230:5230`）读写。仅持久化上面五个 runtime 模型；
`install-bundled-model-weights.sh` 中的模型参数属于 image，不额外挂载。增删 runtime download
service 时同步维护此清单。

不要挂载 `/opt/asr`、`/opt/asr/models` 或整个 `/opt/asr/models/<model>`，否则空 volume 会
遮蔽 image 内的代码、`.venv`、启动脚本和内置参数。HF local-dir metadata 位于对应
`weights/.cache/`，随上述 mount 一起持久化；无需持久化 x 的 uv cache。Runtime HF token
仍只读挂载到 `/home/x/.cache/huggingface/token`，不得和模型参数放在同一 Host 目录。
`/data/asr` 只用于请求期间的临时音频，可单独提供可写 mount，但不作为转写结果或任务状态
的持久化存储。

s6 supervision 本身以 root 运行，业务服务和下载都以固定用户 x 运行。`backtick -x`
仅在 GPU 服务读取本模型 `/run/asr/<model>/CUDA_VISIBLE_DEVICES`；server 读取容器
可见 GPU 池。可选变量缺失时保持 unset，不用空默认值隐藏全部 GPU，不使用 `s6-envdir`。
无环境准备任务，服务重启直接复用已完成的 download oneshot。
各模型的 `timeout-kill`、`flag-timeout-killpg` 与 `finish` 由 s6 执行退出清理；启停入口
仅请求状态切换并等待 finish 结束，不自行轮询 PID。CPU 模型环境使用配套 CPU Torch /
torchaudio wheel，避免拉入无用的 CUDA 依赖。

## Alternatives Outside Scope

保留选型来源用于维护，不创建目录、依赖或配置入口；五套流程不开放任意模型组合。

| 环节 | 未采用候选 / 下载来源 | 部署参考 |
| --- | --- | --- |
| ASR | [FireRedASR2-AED](https://huggingface.co/FireRedTeam/FireRedASR2-AED) | 官方 FireRed SDK，非 vLLM / SGLang 原生 |
| ASR | [Fun-ASR-Nano-2512](https://huggingface.co/FunAudioLLM/Fun-ASR-Nano-2512-vllm) | vLLM 使用 `-vllm`；Omni 使用 `-hf`，另有 FunASR 权重 |
| ASR | [GLM-ASR-Nano-2512](https://huggingface.co/zai-org/GLM-ASR-Nano-2512) | 官方 Transformers；vLLM / SGLang 有原生路径 |
| 热词 ASR | [SeACo-Paraformer](https://www.modelscope.cn/models/iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch) | FunASR hotword checkpoint，与普通 Paraformer 不同 |
| VAD | [TEN-VAD](https://github.com/TEN-framework/ten-vad)、[FSMN-VAD](https://huggingface.co/funasr/fsmn-vad)、[Silero](https://github.com/snakers4/silero-vad) | 分别为官方 ONNX / C、FunASR / ONNX、JIT / ONNX |
| 对齐 | [fa-zh](https://huggingface.co/funasr/fa-zh) | FunASR 音频 + 文本 timestamp prediction |
| 标点 | [CT-Punc](https://huggingface.co/funasr/ct-punc) | FunASR SDK / ONNX |
| Speaker embedding | [CAM++](https://huggingface.co/funasr/campplus) | FunASR embedding，不是完整 diarizer |

Qwen 0.6B、Whisper turbo、MOSS-Audio 其他尺寸 / Thinking 变体也不纳入当前实现。

## CUDA Forward Compatibility

宿主驱动不能升级。H100 属于支持 forward compatibility 的 Data Center GPU；
[NVIDIA 矩阵][cuda-forward] 与 [vLLM 旧驱动说明][vllm-cuda] 支持 CUDA 13 compatibility
mode 配 R535。`nvidia-smi` 的 CUDA Version 是驱动原生能力，不是兼容模式的上限。

- Dockerfile 固定 `cuda-compat-13-0` 包及 SHA256，解压到 `/usr/local/cuda-13.0/compat`。
  仅包含用户态库，不修改宿主内核模块或 ldconfig。
- GPU `run` 在加载 Python 前固定 `LD_LIBRARY_PATH`；vLLM 模型同时固定全局
  `CUDA_HOME`，使 engine 子进程继承 driver compatibility 库与 JIT compiler toolchain。
  其他系统库使用 loader 默认路径；不替换宿主 NVML。
- 这里继承 s6 image，官方 vLLM image entrypoint 的兼容开关不适用。不要仅设置
  `VLLM_ENABLE_CUDA_COMPATIBILITY` 就认为已接入兼容库。
- 检查实际 Torch CUDA runtime、vLLM wheel 与扩展是否成套；compat 只解决驱动接口，
  不解决混装依赖。不要根据旧驱动自动重选 Torch backend 或降级 CUDA。

2026-10-07 在 H100 / R535 `535.161.08` 上，compat `580.178.04-1` 的容器内探针记录：

| 检查 | 原生 R535 用户态库 | CUDA compat |
| --- | --- | --- |
| Driver API | 12020 | 13000 |
| VMM / POSIX FD 分配、映射与导出 | 通过 | 通过 |
| PTX 9.0 JIT / GPU kernel | 错误 222 | 通过 |
| CUDA Graph kernel | 前一步失败，未执行 | 通过 |

这只证明底层接口与 image 接入。真实 Torch 运算、Triton / vLLM 扩展、TP / NCCL 和完整
五方案仍需分别验证；不能把微小 CUDA 探针等同于全部模型运行成功。

## Validation

行为修改运行 `task check:full`，image 相关修改还要从 repository root 构建并做容器验证：

```bash
podman build \
  --secret id=huggingface_token,src=/run/secrets/huggingface_token \
  --file platform/container/services/asr/Dockerfile \
  --tag localhost/codespace-asr:test \
  .
```

| 修改 | 额外验证 |
| --- | --- |
| `run` / `client.py` / s6 | 固定端口匹配；以 x 启动；health 与真实短音频；停止后确认进程退出 |
| download / uv | image 包含固定小模型与全部环境；其余权重不在 image；run/download 不同步环境；验证 uv cache 与 content pass 的跨环境 hardlink |
| 权重 / SDK / vLLM | 锁文件与 import 版本、实际协议响应、截断与时间边界 |
| 融合 / speaker / 时间 | 行为测试与对应真实音频，不以模拟响应宣称质量提升 |
| CUDA / GPU 调度 | 容器内库加载、真实 kernel、所需模型和多 GPU 通信；不停止外部任务 |

已验证 CPU wheel 下的 FireRedVAD 中文音频与 FireRedPunc 标点推理、Nemotron 在 H100 上的
真实多人音频 diarization，s6 下载与服务
链路、异常退出清理和停止超时，以及原子 HTTP 请求的五方案模拟响应、共享证据与
临时音频清理。其余 GPU 模型尚未全部完成真实推理。
已知根检查有无关 Ruff SIM300：`workspace/tools/node-tool/test_node_tool.py:30`；本任务
不修改该文件或用户暂存的 `workspace/config/binman.yaml`。

[vllm-models]: https://github.com/vllm-project/vllm/blob/v0.31.0/docs/models/supported_models.md
[sg-models]: https://github.com/sgl-project/sglang/blob/v0.5.21/docs/docs/supported-models/multimodal_language_models.mdx
[omni]: https://github.com/sgl-project/sglang-omni/tree/v0.1.7
[qwen]: https://github.com/QwenLM/Qwen3-ASR
[firered]: https://github.com/FireRedTeam/FireRedASR2S
[sensevoice]: https://github.com/FunAudioLLM/SenseVoice
[funasr]: https://github.com/modelscope/FunASR
[whisper]: https://github.com/openai/whisper
[moss-td]: https://github.com/OpenMOSS/MOSS-Transcribe-Diarize
[moss-audio]: https://github.com/OpenMOSS/MOSS-Audio
[vibevoice]: https://github.com/microsoft/VibeVoice/blob/main/docs/vibevoice-asr.md
[pyannote]: https://github.com/pyannote/pyannote-audio
[cuda-forward]: https://docs.nvidia.com/deploy/cuda-compatibility/forward-compatibility.html
[vllm-cuda]: https://github.com/vllm-project/vllm/blob/v0.31.0/docs/getting_started/installation/gpu.cuda.inc.md
