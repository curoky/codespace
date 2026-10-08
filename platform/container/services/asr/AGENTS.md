# ASR Maintenance

本目录是普通话完整录音转写服务，产品边界、模型分工与执行流程见 [DESIGN.md](DESIGN.md)。
本文件供 agents 维护实现；模型特有参数的原因、协议限制和坑写在代码旁，不再建每模型
说明文件。版本、端口和 snapshot 的实际值以代码与锁文件为准。

## Model Storage Footprint

下表是当前模型、Serving、依赖栈与存储信息的统一维护入口。全部环境使用 Python 3.12.14；
框架、Torch 和 Transformers 版本来自各目录 `uv.lock` 的 Linux 解析结果。CUDA 是 toolkit
release；CPU-only 环境记为 `—`。大小统一使用二进制 GiB（`1 GiB = 1,073,741,824 bytes =
1024³ bytes`）。

| 模型 / checkpoint | Serving 接口 | SDK / 版本 | Transformers 版本 | vLLM 版本 | Torch 版本 | CUDA 版本 | 参数大小（GiB） | Image 内置 | `.venv` 逻辑大小（GiB） | SGLang 依据 |
| --- | --- | --- | --- | --- | --- | --- | ---: | --- | --- | --- |
| [`firered-llm`](https://huggingface.co/allendou/FireRedASR2-LLM-vllm) | transcription（[作者配方][firered]） | — | 5.17.0 | 0.31.0 | 2.13.0 | 13.0.3 | 31.147 | ❌ | 7.392 | 未找到原生依据 |
| [`firered-punc`](https://huggingface.co/FireRedTeam/FireRedPunc) | 本模型 HTTP | [FireRedASR2S][firered] 0.0.1 @ `4e7d9aa` / CPU | 5.1.0 | — | 2.10.0+cpu | — | 0.762 | ❌ | 0.832 | 未找到原生依据 |
| [`firered-vad`](https://huggingface.co/FireRedTeam/FireRedVAD) | 本模型 HTTP | [FireRedASR2S][firered] 0.0.1 @ `4e7d9aa` / CPU | 5.1.0 | — | 2.10.0+cpu | — | 0.002 | ❌ | 0.832 | 未找到原生依据 |
| [`moss-audio`](https://huggingface.co/OpenMOSS-Team/MOSS-Audio-8B-Instruct) | audio chat（[作者文档][moss-audio]） | — | 5.17.0 | 0.31.0 | 2.13.0 | 13.0.3 | 16.862 | ❌ | 7.392 | 作者 fork |
| [`moss-td`](https://huggingface.co/OpenMOSS-Team/MOSS-Transcribe-Diarize) | transcription（[作者文档][moss-td]） | — | 5.17.0 | 0.31.0 | 2.13.0 | 13.0.3 | 1.692 | ❌ | 7.396 | Omni 原生；主仓库未找到依据 |
| [`nemotron-diarization`](https://huggingface.co/nvidia/Nemotron-3-Diarization) | 本模型 HTTP | NeMo 3.1.0+ca3f93a51 | 4.57.6 | — | 2.13.0 | 13.0.3 | 0.185 | ❌ | 5.288 | 未找到原生依据 |
| [`paraformer`](https://huggingface.co/funasr/paraformer-zh) | 本模型 HTTP | [FunASR][funasr] 1.4.16 | 4.57.6 | — | 2.13.0 | 13.0.3 | 0.820 | ❌ | 4.973 | 未找到原生依据 |
| [`pyannote-community-1`](https://huggingface.co/pyannote/speaker-diarization-community-1) | 本模型 HTTP | [pyannote.audio][pyannote] 4.0.7 | — | — | 2.13.0 | 13.0.3 | 0.031 | ❌ | 4.819 | 未找到原生依据 |
| [`qwen3-aligner`](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B) | pooling + 本模型 HTTP（[Qwen SDK][qwen]） | — | 5.17.0 | 0.31.0 | 2.13.0 | 13.0.3 | 1.709 | ❌ | 7.396 | 未找到等价原生接口 |
| [`qwen3-asr-1.7b`](https://huggingface.co/Qwen/Qwen3-ASR-1.7B) | transcription（[Qwen SDK][qwen]） | — | 5.17.0 | 0.31.0 | 2.13.0 | 13.0.3 | 4.376 | ❌ | 7.392 | 主仓库 / Omni 原生 |
| [`sensevoice`](https://huggingface.co/FunAudioLLM/SenseVoiceSmall) | 本模型 HTTP | [FunASR][sensevoice] 1.4.16 | 4.57.6 | — | 2.13.0 | 13.0.3 | 0.872 | ❌ | 4.973 | 未找到原生依据 |
| [`vibevoice`](https://huggingface.co/microsoft/VibeVoice-ASR-HF) | audio chat（[作者文档][vibevoice]） | — | 5.17.0 | 0.31.0 | 2.13.0 | 13.0.3 | 15.517 | ❌ | 7.392 | 未找到原生依据 |
| [`whisper-large-v3`](https://huggingface.co/openai/whisper-large-v3) | transcription（[模型来源][whisper]） | — | 5.17.0 | 0.31.0 | 2.13.0 | 13.0.3 | 2.875 | ❌ | 7.392 | 主仓库原生 ASR |

参数大小按各 `download_model.sh` 固定 revision 的仓库 metadata 统计，只计算 checkpoint /
weight 文件，不包含 config、tokenizer、词典、CMVN 或 download cache；`.nemo`、`.pth.tar`
等不可拆分 checkpoint 按整个文件计算。`.venv` 是对每个目录独立执行
`du --apparent-size --block-size=1 --summarize` 得到的逻辑大小；共享 hardlink 会在每行
完整计数，不能将各行相加作为 image 物理占用。全部模型均为 `❌`，权重不进入 image。

参数文件总计 76.850 GiB；全部权重、配置、processor 与 tokenizer 都位于 image 外的
`/model-data/<model>`，image 内置权重为 0 GiB。按当前 allowlist，外部模型数据约
76.912 GiB，不含 Hugging Face metadata。13 个 `.venv` 的逻辑大小合计 73.488 GiB；同一
layer 内完成 uv cache 与内容
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
| 外部权重存储 | `/model-data/<model>`；s6 启动依赖按固定 revision 补齐 |
| Python / 依赖版本 | 每目录 `.python-version`、`pyproject.toml`、`uv.lock` |
| 模型地址与请求协议 | `models/<model>/client.py` 的 `URL`、`infer(http, request)` |
| 能力与资源预算 | `models/catalog.py`；不在这里放启动 flags 或端口 |
| 原子请求、转录流程、HTTP 响应 | 本文件 `Server And Pipeline` |
| 文件并发、本地 Markdown / JSON 产物 | `client/asr.py` |
| GPU placement、s6 启停和进程退出 | 本文件 `Static Placement And Operations` |
| image / 用户 / 日志 / 服务依赖 | `Dockerfile`、`rootfs/`；遵循上层 Service runtime 约定 |

只维护五方案用到的模型，不增加通用 worker、参数 launcher、环境准备 job 或动态生成
s6 文件的工具。配置文件使用 YAML，uv 工具文件除外。参数、export 一行一个，逻辑段落
留空行。参数解释贴近实现，仅写约束或理由，不复述命令。

个人使用，一份录音对应一次 HTTP 请求，server 返回结构化 JSON，CLI 控制文件并发并生成
本地 Markdown / JSON 产物；
不引入持久任务队列、任务状态、轮询、幂等键、恢复、部署指纹或跨请求缓存。模型驻留
与 GPU placement 在容器启动时一次确定，请求期间不启停或迁移模型。复杂度主要用于文字、
时间戳和 speaker 的质量约束。

## Server And Pipeline

`api.py` 只接收完整文件并返回五份结果、共享证据与 trace 的结构化 JSON；`transcribe.py`
在一次请求中处理音频与各声道；`recipes.py` 是五套固定流程；`transcript.py` 处理保守选择、
时间与 speaker 映射。server 只通过各模型目录的 client 调 HTTP，不导入模型 SDK，也不生成
ZIP、Markdown、索引或本地文件名。client 校验结构化响应、写入本地产物并给五份 JSON 添加
`evidence.json` 引用。

Server 必须单进程，不能增加 uvicorn workers。`server.yaml` 由 Pydantic 严格解析。image 的
数据目录固定为 `/data/asr`，Host 路径通过 volume 映射；监听参数在 `server/run`，CLI 默认
地址同步维护。`POST /transcribe` 持续等待并返回一次完整响应；临时目录随请求清理，强制
终止后不恢复计算。请求内切片不可变，以模型、切片路径和有效参数做内存复用；失败调用
不缓存，取消请求必须释放模型锁。

原始响应与参数只在响应的 `evidence` 出现一次。`trace` 只记录关键 phase 与实际模型调用的
工程摘要，包括 request cache、GPU UUID / index、模型锁、CPU 排队与推理耗时；不复制原文、
原始响应、模型脚本或整个部署清单。上传与 options 作为不可信 HTTP 输入仍由 server 校验；
模型完成状态、结构、截断和时间边界属于转写正确性，也必须留在 server。展示、文件名和本地
产物完整性校验属于 client。

同一文件固定五套输出。模型失败保留其他可完成方案；缺少旁路校验时明确标记，不覆盖成功
的联合稿。`separate_channels` 逐声道执行并合并为五套结果，speaker 加声道前缀。标点恢复只
允许标点变化；数字、大小写、空格和口语内容不可改写。对齐失败用 null，不能插值补时间；
不把候选置信度跨模型平均。

### Pipeline Invariants

- 同文件先 prepare、四路 first pass、整批 review，再生成五套方案。prepare 先跑全文件
  pyannote，再取 VAD 与 speaker 活动并集。短窗按同一原音与 padding 提供给各路候选，不能
  互喂答案。first pass 的四个模型并行处理各自的整批窗口，同一模型内仍逐窗串行。
- 只有分歧、空识别或异常重复触发扩窗复听。先听 Qwen / FireRed / Whisper，仍未解决才调
  MOSS-Audio。前三个复听模型并行处理各自的整批争议窗口，每个模型内部逐窗串行并集中
  对齐；三批全部结束后才判断是否需要 MOSS-Audio。同模型重复采样与同家族不增加独立
  票数；两份融合稿不能读取对方定稿。
- 文字替换要求主模型复听也改口且独立家族支持。数值、热词、英文专名启发式和多人活动
  窗口受保护；保留 raw、候选、复核依据和未解决标记。
- 联合模型按长窗输出自身正文、时间和局部 speaker。用 pyannote 单人活动映射到全文身份，
  映射歧义保持未知；四路校验只提供分歧标记，不改写联合稿。
- 联合窗口的结构、时间范围与活动尾部须校验；失败最多缩窗重试两层。按字词时间裁剪核心
  区间，边界无法对齐则失败。全部时间还原为原音整数毫秒；speaker 可多人或未知，同一句
  正文不因多人标签重复。
- 第五稿依赖第一稿文字与时间，只用 Nemotron 重标 speaker。已知全文超过 8 人时失败，
  未知人数标 `unverified_max_8`，pyannote 观察到超限标 `suspected_out_of_scope`。

## Static Placement And Operations

`server.yaml` 按逻辑可见 GPU 序号固定全部 GPU 模型的 placement；当前 80 GiB 预算使用 5 卡，
每卡合计分别为 64 / 50 / 60 / 60 / 12 GiB。5 卡不是按模型摊开：FireRed TP=2 固定占两张，
first pass 的 Qwen / SenseVoice / Paraformer 分别使用另外三张，因此这是隔离四条并行模型
lane 的最小卡数；review 的 FireRed / Qwen / Whisper / Aligner 也互不共卡。只在其他阶段执行
的常驻模型复用这五张卡。这个布局与 `models/catalog.py` 的每模型预算和各 vLLM
`gpu_memory_utilization` 是一个维护单元。deployment test 离线校验模型集合、TP 卡数、单卡
总量、并发阶段互斥和 vLLM 比例。placement 不写 Host 物理卡号；`scheduler.py` 在容器启动
时把逻辑序号映射到可见 GPU UUID，检查实际卡数与空闲显存，然后依次启动全部 CPU / GPU
模型并等待 health。请求期间只保留每模型一个在途请求锁和 CPU semaphore，不启停、回收、
迁移或降级模型。

模型 client 提供固定 `URL` 与 `infer(http, request)`；scheduler 不生成监听参数。启动前只向
GPU 模型的 `/run/asr/<model>/CUDA_VISIBLE_DEVICES` 写入固定 placement 对应的 UUID；CPU
模型不写环境文件。`processes.py` 负责有超时的子进程、GPU inventory，并调用 root-owned
`/usr/local/bin/asr-model-service` 请求固定 s6 graph 的 start / stop；sudoers 只授权 x 调用
这个入口。shared s6 live state 仍由 root 管理，不修改权限，也不增加管理 RPC。

停止由 s6 发 TERM；`timeout-kill` / `flag-timeout-killpg` 超时终止进程组。模型 run 退出后，
`finish` 以 x 清理残留 engine 子进程，覆盖异常退出。容器 shutdown 由 s6 graph 并行停止
server 和全部模型；server 只关闭自己的 HTTP client，不能在 lifespan shutdown 中再次逐个
请求 s6 停模型，否则会与 graph teardown 竞态。模型 HTTP 请求失败不触发停服，进程异常由
s6 supervision 处理。独立排查模型时先停止容器服务，再在模型目录运行锁定环境中的
`download_model.sh` 或 `run`，不要在运行中的 server 外手动改变 s6 状态。

## Model Contract

- `install-model-environments.sh` 在 image build 的同一个 layer 中遍历全部模型并使用
  `UV_LINK_MODE=hardlink` 创建独立 `.venv`；server 安装完成后再对所有环境做 content-based
  hardlink，补齐 uv cache artifact 之外的相同文件。CUDA toolkit meta package、compiler、
  CRT 与 NVVM 由 image 全局提供，安装时跳过 vLLM kernel package 间接声明的对应 wheel。
  任一 lock 失配、安装或去重失败必须使 build 失败。
- `run` 与 `download_model.sh` 使用 `uv run --frozen --no-sync`，只运行 image 内预装环境，
  不在启动或手动下载权重时解析、安装或更新依赖。
- 每个模型目录的 `weights` 是 image 内固定 symlink，指向 `/model-data/<model>`。下载脚本只
  调用 HF CLI；`run` 只加载挂载权重，不代替下载。下载脚本先创建 symlink 的实际目标，
  因此空的 runtime mount 不会把 image 构建期目录遮蔽成 dangling symlink。
  下载脚本用显式 include 只取 serving 所需的权重格式、配置、processor 与自定义模型代码，
  不下载同一 checkpoint 的其他框架或精度副本。HF 根据 local-dir metadata 复用文件。
  成功后将 revision 写入 `.revision`；匹配时立即返回，不访问 Hugging Face。image build 不
  访问 Hugging Face；容器启动时由 s6 download oneshot 补齐缺失或过期 snapshot。改变
  revision 时无需兼容旧 marker；本地 `.venv` 与权重不进入 build context。
- 监听地址和端口在 `run` 显式固定，client 的 `URL` 同步维护。调度器从 client 读取地址
  做 readiness，不生成端口，也不把地址注入模型。改变端口时同步 DESIGN 的服务表。
- vLLM transcription 的 `SpeechToTextConfig` 由各 model class 从 processor 构造，`run`
  不传 server 级覆盖参数。普通 ASR 由上层保持不超过 30 秒，catalog 记录相同模型预算；
  联合模型根据 catalog 的上限切窗。升级 vLLM 时核对模型实现与 CLI parser，不能只依据
  旧启动参数。
- VibeVoice 必须沿用上游 transcription request。vLLM 不会替换 HF checkpoint 模板中的
  `<|AUDIO_DURATION|>`，因此 `run` 固定使用本目录模板，client 通过
  `chat_template_kwargs` 传入实际 WAV 时长；audio data URL 和固定输出字段缺一不可，否则
  模型会越过真实音频尾部重复生成。生成预算与总上下文预算按上游长音频配置成对维护；
  总上下文必须同时容纳音频 prompt 和完整结构化输出。
- SDK 服务只接收 `/data/asr` 内真实文件；原生 vLLM client 发送音频内容。数据目录是镜像
  内固定契约，改变 Host 存储位置用 bind mount；不要只改 server 的路径而破坏 SDK 访问。
- 模型不读取应用配置环境变量。GPU 服务的唯一动态输入是 `CUDA_VISIBLE_DEVICES`：由启动期
  static placement 映射后经 s6 传入。不要 hardcode 物理卡号；SDK 的 `cuda:0` 表示本进程
  可见的第一张卡。
  CPU 服务无需这项输入。
- `run` 固定 offline、线程预算等必要环境；vLLM 的 `CUDA_HOME` 指向 image 全局
  `/usr/local/cuda-13.0`，其 `bin` 由 image 加入 `PATH`，供 FlashInfer runtime JIT 使用。
  toolkit 从固定 digest 的 NVIDIA CUDA devel image 取 compiler、headers、NVVM、CUDA runtime
  linker inputs 与 driver stub，不从模型 venv 选择 compiler；FlashInfer 的 NVRTC 与 GPU runtime
  libraries 仍由 venv 的锁定依赖提供。vLLM 的 `LD_LIBRARY_PATH` 固定为 image 内 CUDA compat
  和 toolkit `lib64` 目录，不含仅供链接的 driver stub。不要拼接 Host 的库路径、代理或 uv /
  HF 环境变量。
- 模型间不共用 `.venv`。SDK 的 Torch / torchaudio 必须成套；不要为了统一版本而与 vLLM
  混装。修改 TP、精度、显存利用率或上下文预算后同步 catalog 与 `server.yaml` placement。
  vLLM 显存比例是同卡多个进程共同使用的静态上限，不是模型精确占用；比例之和与 SDK
  预算必须给 CUDA context 和运行波动留余量。
- HF token 在手动下载或首次容器启动时通过 `/run/secrets/huggingface_token` 提供；pyannote
  需预先接受模型访问条件。token 不写入脚本、命令行、image layer 或 `/model-data`。

## Image And S6

镜像继承 `service-s6`，在构建时安装系统工具、Python、server 与全部模型环境，并编译静态
graph；镜像不包含任何模型权重。全部环境必须在同一 `RUN`、同一 filesystem 中创建，先依靠 uv
cache hardlink 去重，再用 util-linux `hardlink` 比较内容并合并剩余副本；后一步保留 mode、
owner 和 xattr，只忽略 mtime，并优先复用 link count 最高的 inode。Python 与环境安装使用
Dockerfile 的 `USER x`，cache 在对应 `RUN` 结束前删除；s6 graph 切回 root 编译。每个
`weights` symlink 由 Dockerfile 固定创建，统一落到 `/model-data` mount。

| 资产 | 维护约定 |
| --- | --- |
| `rootfs/etc/s6/s6-rc.d/asr-<model>-download/` | oneshot；revision marker 命中时立即完成，否则下载固定 snapshot |
| `rootfs/etc/s6/s6-rc.d/asr-<model>/` | longrun；依赖本模型 download oneshot |
| `rootfs/etc/s6/s6-rc.d/asr-server/` | 以 x 调 `server/run`；server 环境已在构建时安装，使用 `--no-sync` |
| `install-model-environments.sh` | build-only；顺序安装全部锁定模型环境并强制 uv cache hardlink，失败立即终止 |
| `rootfs/usr/local/bin/asr-model-service` | root-owned 受限启停入口，由 sudoers 仅授权 x 调用 |
| `/var/log/s6.asr-*.log` | `redirfd -w` + `fdmove`，沿用 Workspace 日志范式 |
| `/data/asr` | 请求临时音频，Host mount 必须允许 x 写入；正常结束与异常返回均清理 |

### Runtime Mounts

正常部署为全部模型参数提供一个可写 bind mount，首次启动自动下载并持久化：

```yaml
volumes:
  - ${RESOURCE_DATA}/models:/model-data
```

Host 目录可以初始为空，但必须允许容器用户 x（UID/GID `5230:5230`）写入。download oneshot
在模型启动前补齐固定 snapshot 并写入 revision marker；后续容器只做本地 marker 检查。
不提供 mount 时仍可下载到容器内 `/model-data`，但容器替换后不会保留。本地开发先在
`/workspace/model-data` 手动准备全部权重，再以只读方式挂载；具体流程由项目级 `test-asr`
skill 维护。

FireRed TP / NCCL 需要的 POSIX shared memory 超过 Podman 默认值。正常 Service 声明和本地
测试都固定分配 `shm_size: 8g`；不要用默认 64 MiB，也不要为了绕过容量约束改成 host IPC。

不要挂载 `/opt/asr`、`/opt/asr/models` 或整个 `/opt/asr/models/<model>`，否则会遮蔽 image
内的代码、`.venv` 和启动脚本。HF local-dir metadata 位于 `/model-data/<model>/.cache/`，随
统一 mount 持久化；无需持久化 x 的 uv cache。自动下载需要把 HF token 只读挂载到
`/run/secrets/huggingface_token`，并设置为 x（UID/GID `5230:5230`）可读；marker 全部命中时
不会读取 token。
`/data/asr` 只用于请求期间的临时音频，可单独提供可写 mount，但不作为转写结果或任务状态
的持久化存储。

s6 supervision 本身以 root 运行，业务服务和下载以固定用户 x 运行。`backtick -x`
仅在 GPU 服务读取本模型 `/run/asr/<model>/CUDA_VISIBLE_DEVICES`；server 启动时一次读取
容器可见 GPU 池并启动全部模型。可选变量缺失时保持 unset，不用空默认值隐藏全部 GPU，
不使用 `s6-envdir`。下载只发生在模型 service 的启动依赖中，请求期间不检查或修改权重。
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
  --file platform/container/services/asr/Dockerfile \
  --tag localhost/codespace-asr:test \
  .
```

| 修改 | 额外验证 |
| --- | --- |
| `run` / `client.py` / s6 | 固定端口匹配；以 x 启动；health 与真实短音频；停止后确认进程退出 |
| download / uv | image 不含任何权重且包含全部环境；run/download 不同步环境；验证 uv cache 与 content pass 的跨环境 hardlink |
| 权重 / SDK / vLLM | 锁文件与 import 版本、实际协议响应、截断与时间边界 |
| 融合 / speaker / 时间 | 行为测试与对应真实音频，不以模拟响应宣称质量提升 |
| CUDA / static placement | 五卡同时驻留、实际空闲余量、真实 kernel、TP / NCCL 与跨模型并发；其余可见卡保持空闲，不停止外部任务 |

已验证 CPU wheel 下的 FireRedVAD 中文音频与 FireRedPunc 标点推理、Nemotron 在 H100 上的
真实多人音频 diarization，s6 服务链路、异常退出清理和停止超时，以及原子 HTTP
请求的五方案模拟响应、共享证据与临时音频清理。真实 GPU 验证必须使用项目级 `test-asr`
skill，不能以离线预算、模拟响应或 image build 替代容器启动与完整推理。

2026-10-09 在 8×H100 80 GiB / R535 Host 上只映射前 5 卡完成真实 30 秒音频验证：13 个模型
全部调用，五份结果均完成，trace 总耗时 13.521 秒且无失败事件；first pass 四路从
962–963 ms 同时开始，review 的 Qwen / FireRed / Whisper 均从 2157 ms 开始，MOSS-Audio
在前三批结束后从 3276 ms 开始。请求后五卡占用为
60,754 / 32,506 / 52,304 / 50,288 / 6,958 MiB，
其余三卡为 0；全部服务无 OOM、shared-memory 错误或重启。该结果证明当前 placement 与
并发时序可运行，不代表其他 GPU 容量、driver 或模型 revision。

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
