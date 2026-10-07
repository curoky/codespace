# ASR Maintenance

本目录是普通话完整录音转写服务，产品边界、模型分工与执行流程见 [DESIGN.md](DESIGN.md)。
本文件供 agents 维护实现；模型特有参数的原因、协议限制和坑写在代码旁，不再建每模型
说明文件。版本、端口和 snapshot 的实际值以代码与锁文件为准。

## Context And Ownership

| 修改内容 | Source of truth / 先读 |
| --- | --- |
| 模型启动、参数、环境 | `models/<model>/run`；SDK 参数在同目录 `service.py` |
| 权重来源与格式 | `models/<model>/download_model.sh` 的 repo、revision、include |
| Python / 依赖版本 | 每目录 `.python-version`、`pyproject.toml`、`uv.lock` |
| 模型地址与请求协议 | `models/<model>/client.py` 的 `URL`、`infer(http, request)` |
| 能力与资源预算 | `models/catalog.py`；不在这里放启动 flags 或端口 |
| 核心流程、缓存、产物 | [server/AGENTS.md](server/AGENTS.md) |
| GPU、s6 启停和进程退出 | [ops/AGENTS.md](ops/AGENTS.md) |
| image / 用户 / 日志 / 服务依赖 | `Dockerfile`、`rootfs/`；遵循上层 Service runtime 约定 |

只维护五方案用到的模型，不增加通用 worker、参数 launcher、环境准备 job 或动态生成
s6 文件的工具。配置文件使用 YAML，uv 工具文件除外。参数、export 一行一个，逻辑段落
留空行。参数解释贴近实现，仅写约束或理由，不复述命令。

## Model Contract

- `run` 与 `download_model.sh` 可在 image 内独立执行，使用 `uv run --locked --no-dev`
  创建或同步本目录 `.venv`；lock 与 project 不一致即失败，不自动更新依赖。
- 权重固定在本目录 `weights/`。下载脚本只调用 HF CLI；`run` 只加载本地权重，不代替下载。
  HF 根据 local-dir metadata 复用文件。改变 revision 时先停止模型并清理旧 weights，
  避免旧文件混入；不得把本地 `.venv` 或权重打包进 image。
- 监听地址和端口在 `run` 显式固定，client 的 `URL` 同步维护。调度器从 client 读取地址
  做 readiness，不生成端口，也不把地址注入模型。改变端口时同步 DESIGN 的服务表。
- SDK 服务只接收 `/data/asr` 内真实文件；原生 vLLM client 发送音频内容。数据目录是镜像
  内固定契约，改变 Host 存储位置用 bind mount；不要只改 server 的路径而破坏 SDK 访问。
- 模型不读取应用配置环境变量。GPU 服务的唯一动态输入是 `CUDA_VISIBLE_DEVICES`：由
  ops 分配、s6 传入。不要 hardcode 物理卡号；SDK 的 `cuda:0` 表示本进程可见的第一张卡。
  CPU 服务无需这项输入。
- `run` 固定 offline、线程预算等必要环境；GPU 的 `LD_LIBRARY_PATH` 固定为 image 内
  CUDA compat 目录。不要拼接 Host 的库路径、代理或 uv / HF 环境变量。
- 模型间不共用 `.venv`。SDK 的 Torch / torchaudio 必须成套；不要为了统一版本而与 vLLM
  混装。修改 TP、精度、显存利用率或上下文预算后同步 catalog 的资源 / 时长限制。
  显存利用率是独占设备上的预算，不是模型精确需求。
- HF token 使用 x 默认的 `/home/x/.cache/huggingface/token`，只读挂载且 x 可读。
  pyannote 需预先接受模型访问条件；不把 token 写进脚本或命令行。

## Image And S6

镜像继承 `service-s6`，只在构建时安装系统工具、Python 与 server 环境，编译静态 graph。
模型环境与权重都在运行时准备。uv 的 Python 和 cache、HF 的 cache / token 使用 x 默认
目录，不转发工具或代理环境变量。

| 资产 | 维护约定 |
| --- | --- |
| `rootfs/etc/s6/s6-rc.d/asr-<model>-download/` | oneshot，以 x 调本模型 `download_model.sh` |
| `rootfs/etc/s6/s6-rc.d/asr-<model>/` | longrun，依赖对应 download，以 x 调本模型 `run` |
| `rootfs/etc/s6/s6-rc.d/asr-server/` | 以 x 调 `server/run`；server 环境已在构建时安装，使用 `--no-sync` |
| `rootfs/usr/local/bin/asr-model-service` | root-owned 受限启停入口，由 sudoers 仅授权 x 调用 |
| `/var/log/s6.asr-*.log` | `redirfd -w` + `fdmove`，沿用 Workspace 日志范式 |
| `/data/asr` | 持久任务数据，Host mount 必须允许 x 写入 |
| 模型 `weights/`、x 的 uv cache | 可持久化；不要用空 volume 覆盖整个 `/opt/asr` |

s6 supervision 本身以 root 运行，业务服务和下载都以固定用户 x 运行。`backtick -x`
仅在 GPU 服务读取本模型 `/run/asr/<model>/CUDA_VISIBLE_DEVICES`；server 读取容器
可见 GPU 池。可选变量缺失时保持 unset，不用空默认值隐藏全部 GPU，不使用 `s6-envdir`。
无环境准备任务，服务重启直接复用已完成的 download oneshot。

## Serving Compatibility

以下为 2026-10-07 的上游核对记录，依据 [vLLM 0.31.0][vllm-models]、
[SGLang 0.5.21][sg-models]、[SGLang-Omni 0.1.7][omni]。它说明部署接口依据，不代替
当前 Host 的真实推理验证；升级时重新核对实际 model class、endpoint 和 response schema。
SGLang 主仓库、Omni 与作者 fork 是不同 runtime。OpenAI-compatible HTTP 不等于模型原生支持。

| 当前模型 / 下载来源 | 官方部署依据 | 本项目 Serving | SGLang 依据 |
| --- | --- | --- | --- |
| [Qwen3-ASR-1.7B](https://huggingface.co/Qwen/Qwen3-ASR-1.7B) | [Qwen SDK][qwen] 支持并推荐 vLLM 加速 | 原生 vLLM transcription，普通权重 | 主仓库 / Omni 原生 |
| [FireRedASR2-LLM 转换版](https://huggingface.co/allendou/FireRedASR2-LLM-vllm) | [作者][firered] 引用该社区转换版及 vLLM 配方 | 原生 vLLM transcription | 未找到原生依据 |
| [SenseVoiceSmall](https://huggingface.co/FunAudioLLM/SenseVoiceSmall) | [官方][sensevoice] FunASR AutoModel / FastAPI | FunASR SDK；无所需 vLLM 原生接口 | 未找到原生依据 |
| [Paraformer-zh](https://huggingface.co/funasr/paraformer-zh) | [FunASR][funasr] AutoModel / ONNX / C++ | FunASR SDK；无所需 vLLM 原生接口 | 未找到原生依据 |
| [Whisper large-v3](https://huggingface.co/openai/whisper-large-v3) | [OpenAI SDK / CLI][whisper]；框架适配由框架维护者提供 | 原生 vLLM transcription | 主仓库原生 ASR |
| [MOSS-Transcribe-Diarize](https://huggingface.co/OpenMOSS-Team/MOSS-Transcribe-Diarize) | [作者][moss-td] 推荐 Omni，另有 vLLM / Transformers | 原生 vLLM transcription，解析结构化输出 | Omni 原生；主仓库未找到依据 |
| [VibeVoice-ASR-HF](https://huggingface.co/microsoft/VibeVoice-ASR-HF) | [作者][vibevoice] 文件推理与旧 vLLM plugin | stable vLLM 原生 HF architecture，audio chat | 未找到原生依据 |
| [MOSS-Audio-8B-Instruct](https://huggingface.co/OpenMOSS-Team/MOSS-Audio-8B-Instruct) | [作者][moss-audio] Transformers 与自己的 SGLang fork | 原生 vLLM audio chat | 作者 fork；主仓库未找到依据 |
| [Qwen3-ForcedAligner-0.6B](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B) | [Qwen SDK][qwen] 完整对齐 API | vLLM pooling / token_classify + 本目录解码 API | 未找到等价原生接口 |
| [pyannote community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) | [pyannote.audio][pyannote] Pipeline.from_pretrained | 官方 SDK；无原生 vLLM API | 未找到原生依据 |
| [Nemotron-3-Diarization](https://huggingface.co/nvidia/Nemotron-3-Diarization) | 官方 NeMo offline diarize，另有 Transformers / NeMo-Speech.cpp | NeMo SDK；无原生 vLLM API | 未找到原生依据 |
| [FireRedVAD](https://huggingface.co/FireRedTeam/FireRedVAD) | [FireRedVad][firered] SDK | 官方 SDK / CPU；无原生 vLLM API | 未找到原生依据 |
| [FireRedPunc](https://huggingface.co/FireRedTeam/FireRedPunc) | [FireRedPunc][firered] SDK | 官方 SDK / CPU；无原生 vLLM API | 未找到原生依据 |

上游 revision、权重格式、SDK 版本与启动参数必须一起核对。Qwen 普通 / `-hf`、VibeVoice
原版 / HF、FireRed 原始 / 转换权重不能互换。FunASR 的 `paraformer-zh` 简称在不同 hub
映射不同，始终以本目录下载脚本的完整 repo 为准。

### Alternatives Outside Scope

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
- GPU `run` 在加载 Python 前固定 `LD_LIBRARY_PATH`，使 engine 子进程也继承。
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
  --file platform/container/services/asr/Dockerfile \
  --tag localhost/codespace-asr:test \
  .
```

| 修改 | 额外验证 |
| --- | --- |
| `run` / `client.py` / s6 | 固定端口匹配；以 x 启动；health 与真实短音频；停止后确认进程退出 |
| download / uv | image 无权重和模型环境；首次下载自动建环境；删除环境后 run 可重建 |
| 权重 / SDK / vLLM | 锁文件与 import 版本、实际协议响应、截断与时间边界 |
| 融合 / speaker / 时间 | 行为测试与对应真实音频，不以模拟响应宣称质量提升 |
| CUDA / GPU 调度 | 容器内库加载、真实 kernel、所需模型和多 GPU 通信；不停止外部任务 |

已验证 FireRedVAD 真实中文输入、s6 下载与服务链路、两个脚本自动创建环境、五方案
模拟响应及部分失败行为。其余模型尚未完成真实 GPU 推理，pyannote 授权下载尚未验证。
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
