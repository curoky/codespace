# Chinese Recording Transcription

把完整的普通话对话录音转成**带时间戳、说话人和待核对标记的原话记录**。
每个文件固定产出 **5 份 Markdown + 5 份 JSON + 索引 + 共享证据 + 执行追踪**。一次 HTTP
请求返回结构化结果、证据和 trace，CLI 将其原子写成本地产物。中文为主，保留夹杂英文、
语气词、重复和插话。

| 输入 | 处理 | 输出 | 部署 |
| --- | --- | --- | --- |
| 完整录音文件或目录 | VAD → 多模型识别与复核 → 标点 / 对齐 / speaker | 五套转录文档及证据 JSON | 一个 Linux 容器 + Python CLI |

不处理粤语、实时流、翻译、摘要或跨文件身份识别；不需要网页、数据库或外部队列。
维护入口是 [AGENTS.md](AGENTS.md)，模型参数的原因和约束直接写在实现旁的注释中。

## Architecture

```mermaid
flowchart LR
    CLI[Python CLI<br/>控制文件并发、接收结果]
    subgraph Container[单个 Linux 容器]
        API[HTTP server<br/>0.0.0.0:8080]
        Pipeline[本次请求的五方案编排<br/>共享内存响应]
        Ops[ops<br/>启动期 static placement]
        S6[s6<br/>启动期下载与模型监督]
        Client[每模型 client.py]
        Model[每模型服务<br/>127.0.0.1:8000–8012]
        Data[临时音频<br/>/data/asr]
        API --> Pipeline
        Pipeline --> Client
        Client -->|原生 HTTP 协议| Model
        Pipeline --> Ops
        Ops -->|受限 Shell 入口| S6
        S6 -->|启动期 download / run| Model
        Pipeline --> Data
    end
    CLI <-->|HTTP| API
```

| 层次 | 拥有的职责 | 交互方式 |
| --- | --- | --- |
| `client/asr.py` | 文件并发、本地 Markdown / JSON 展示与原子发布 | 上传文件并消费结构化响应 |
| 上层 `server/` | 一次请求内的音频处理、五方案、文字选择、时间、身份与证据 | 调用模型 client，不导入模型 SDK |
| 底层 `models/<model>/` | 本模型 Python 环境、权重下载、参数、服务与 HTTP 协议 | 从 `/model-data` 读取外部权重；官方支持时原生 vLLM |
| 运维 `ops/` + `rootfs/` | static GPU placement、启动期部署、进程监督、用户与日志 | ops 请求 s6 操作，s6 执行静态脚本 |

每模型一个实例、一个固定端口、一个独立 uv 环境。全部模型在容器 ready 前按
`server.yaml` 的逻辑 placement 驻留；多个方案共享实例，placement 不绑定 Host 物理卡号。
文件并发由 CLI 控制。服务端没有文件队列、任务 ID、状态查询、重启恢复或跨请求缓存。

## Project Layout

```text
asr/
├── DESIGN.md                 # 架构与执行流程
├── AGENTS.md                 # 维护约定、框架兼容与验证边界
├── Dockerfile
├── protocol.py               # 请求、时间片与结果契约
├── client/asr.py              # 独立 Python CLI、本地产物生成
├── server/
│   ├── run / server.yaml      # HTTP 入口 / 编排配置
│   ├── api.py / transcribe.py # HTTP 请求 / 完整文件处理
│   ├── audio.py / recipes.py  # 音频处理与五方案
│   └── inference.py / transcript.py / tracing.py
├── models/
│   ├── catalog.py            # 模型能力、时长限制与资源预算
│   ├── vllm.py               # vLLM 响应完成状态解析
│   └── <model>/
│       ├── pyproject.toml / uv.lock / .python-version
│       ├── download_model.sh # 固定 repo / revision，供 image 外手动准备权重
│       ├── run               # 监听地址、端口及模型启动参数
│       ├── client.py         # 固定服务地址、请求与结果解析
│       ├── service.py        # 仅 SDK / 特殊 pooling 接口需要
│       └── .venv/ / weights  # 镜像构建环境；weights 链接到 /model-data/<model>
├── ops/                      # GPU inventory、调度与进程操作
├── rootfs/
│   ├── etc/s6/s6-rc.d/        # 全部静态 s6 定义
│   ├── etc/sudoers.d/asr
│   └── usr/local/bin/asr-model-service
└── tests/
```

## Model Services

13 个模型分工如下，**11 个常规使用，2 个仅在争议时复核**。端口按目录名顺序约定，
直接写在各模型的 `run` 与 `client.py`，调度器不生成端口。所有模型只监听 loopback，
对外仅发布 HTTP server 的 `8080`。

| 端口 | 模型目录 | 模型 / 职责 | Serving |
| --- | --- | --- | --- |
| 8000 | `firered-llm` | FireRedASR2-LLM：第二主稿与交叉校验 | vLLM transcription |
| 8001 | `firered-punc` | FireRedPunc：融合稿标点 | FireRed SDK / CPU |
| 8002 | `firered-vad` | FireRedVAD：语音活动范围 | FireRed SDK / CPU |
| 8003 | `moss-audio` | MOSS-Audio-8B-Instruct：仍有争议时复听 | vLLM audio chat |
| 8004 | `moss-td` | MOSS-Transcribe-Diarize：联合文字、时间和 speaker | vLLM transcription |
| 8005 | `nemotron-diarization` | Nemotron-3-Diarization：独立 speaker 结果 | NeMo SDK |
| 8006 | `paraformer` | Paraformer-zh：独立中文校验 | FunASR SDK |
| 8007 | `pyannote-community-1` | pyannote：全文件身份与跨窗映射 | pyannote.audio SDK |
| 8008 | `qwen3-aligner` | Qwen3-ForcedAligner-0.6B：定稿字词时间 | vLLM pooling + 本模型 HTTP |
| 8009 | `qwen3-asr-1.7b` | Qwen3-ASR-1.7B：第一主稿与交叉校验 | vLLM transcription |
| 8010 | `sensevoice` | SenseVoiceSmall：独立中文校验 | FunASR SDK |
| 8011 | `vibevoice` | VibeVoice-ASR-HF：另一套联合转录 | vLLM audio chat |
| 8012 | `whisper-large-v3` | Whisper large-v3：争议区间复听 | vLLM transcription |

## Image Startup Pipeline

```mermaid
flowchart TD
    subgraph Build[镜像构建]
        B1[service-s6 基础镜像] --> B2[系统工具 / Python / CUDA 兼容库]
        B2 --> B3[复制代码与 rootfs<br/>安装全部环境，编译 s6 graph]
    end
    subgraph Boot[容器启动]
        B3 --> I[s6 init / root supervision]
        I --> S[以 x 执行 server/run]
        S --> R[停止本容器遗留模型实例<br/>初始化资源记录]
        R --> H[HTTP ready<br/>接收转录请求]
    end
    subgraph Deploy[Server 启动期静态部署]
        R --> A[读取可见 GPU<br/>映射逻辑 placement 并检查空闲显存]
        A --> D{s6 download oneshot<br/>revision marker 匹配?}
        D -->|否| U[下载固定 snapshot<br/>写入 marker]
        D -->|是| M[s6 longrun<br/>以 x 执行模型 run]
        U --> M
        M --> V[预装环境加载本地 weights<br/>等待 health]
        V --> H[全部模型 ready<br/>接收转录请求]
    end
```

| 时机 | 实际行为 |
| --- | --- |
| 构建镜像 | 安装 server 和全部模型环境；不下载或复制任何模型权重，也不需要 HF secret |
| 本地准备权重 | 在 image 外手动运行固定 `download_model.sh`，写入 `/workspace/model-data/<model>` 与 marker |
| 正常部署首次启动 | s6 oneshot 用 runtime HF secret 自动下载缺失或过期 snapshot，再启动模型 |
| 已准备权重的启动 | marker 命中后不访问 HF，直接从 `/model-data` 加载；本地可只读挂载 |
| 容器重建 | 持久 model-data 继续复用；image rebuild 不读取或修改权重 |
| 卡数或显存不足 | 启动失败；不在请求期迁移、回收或降级模型 |
| 模型退出 | s6 graph 并行停止全部服务；finish 清理残留子进程，server 不重复发 stop |

s6 负责进程与依赖，ops 在启动期把配置中的逻辑卡映射为可见 GPU UUID。模型固定使用
`/data/asr` 读取音频；端口、路径、精度等参数均在模型目录内维护。请求期间每模型用一个
锁串行调用，不再包含 GPU queue 或服务启停。

当前 placement 使用 5 张 80 GiB GPU。FireRed TP=2 已占两张；为让 first pass 的另外三个
模型不共卡，至少还需要三张，因此 5 卡是本 pipeline 的并发下限，不按模型数量继续扩卡。
只在其他阶段运行的常驻模型复用相同 GPU：

| 逻辑 GPU | 常驻模型 | 离线预算 | 并发边界 |
| ---: | --- | ---: | --- |
| 0 | FireRed、MOSS-Audio | 64 GiB | MOSS-Audio 在三路 review 完成后才运行 |
| 1 | FireRed、Pyannote、Nemotron | 50 GiB | 后两者分别只在 prepare / 第五方案运行 |
| 2 | Qwen ASR、MOSS-TD | 60 GiB | first pass / review 与第三方案错开 |
| 3 | SenseVoice、Whisper、VibeVoice | 60 GiB | 三者分别位于 first pass / review / 第四方案 |
| 4 | Paraformer、Qwen Aligner | 12 GiB | first pass 结束后才开始对齐 |

正常 Service 通过可写 `/model-data` mount 在首次启动自动下载权重；本地测试使用预下载的
只读 mount。两者都必须提供 8 GiB `/dev/shm`，避免 FireRed TP / NCCL 落入 Podman 默认
64 MiB shared memory。仓库中的完整部署示例以 `config.example.yaml` 为准。

## Request Pipeline

一个文件按下图执行；五套方案共享本次请求内的计算。CLI 用 `--parallel` 限制文件
并发，每个模型一次处理一个调用。HTTP 连接保持到完整结果返回，不需要轮询。

```mermaid
flowchart TD
    C[CLI 上传完整文件] --> U[POST /transcribe<br/>原音写入本次请求临时目录]
    U --> F[FFmpeg 解码<br/>mono 16 kHz PCM，保留原始时间轴]
    F --> P[pyannote 全文件 speaker<br/>FireRedVAD 活动与 speaker 活动取并集]
    P --> W[统一切短窗]
    W --> A[四路并行第一轮识别<br/>Qwen / FireRed / SenseVoice / Paraformer]
    A --> R[收集争议窗口<br/>Qwen / FireRed / Whisper 三批并行复听]
    R --> R1[01 Qwen 主稿融合]
    R1 --> R2[02 FireRed 主稿融合<br/>复用四路候选与复听响应]
    R2 --> R3[03 MOSS-TD 联合转录<br/>带重叠的长窗口]
    R3 --> R4[04 VibeVoice 联合转录<br/>带重叠的长窗口]
    R4 --> R5[05 复用 01 的文字与时间<br/>Nemotron 重新标注 speaker]
    R5 --> O[组装五套结果、共享证据与 trace<br/>清理临时音频]
    O --> D[HTTP 返回结构化 JSON]
    D --> A[CLI 生成 Markdown / JSON<br/>原子发布本地结果目录]
```

`--separate-channels` 对独立录制的声道分别执行流程，再合并成相同五套产物；
speaker 加声道前缀。`--vad-off` 使用全文活动范围。默认不降噪、不做音源分离。

| 方案 | 正文来源与复核 | Speaker | 定稿后处理 |
| --- | --- | --- | --- |
| `01-qwen-fusion` | Qwen 主稿；FireRed / SenseVoice / Paraformer 校验，争议时复听 | 全文件 pyannote | FireRedPunc → Qwen aligner → 按字词活动分配身份 |
| `02-firered-fusion` | FireRed 主稿；共享四路候选和复听响应，独立裁定 | 共享 pyannote | 同 `01`，正文不同时重新对齐 |
| `03-moss-td` | MOSS-TD 原生正文；已有四路分歧只用于标记 | 局部标签通过 pyannote 映射到全文件身份 | 保留原生标点和片段时间，Qwen aligner 补字词时间 |
| `04-vibevoice` | VibeVoice 原生正文；已有四路分歧只用于标记 | 同 `03` | 同 `03` |
| `05-qwen-nemotron` | 直接复用 `01`，不重新识别或对齐 | Nemotron 全文件处理，最多 8 个身份 | 仅重新分配 speaker；间接继承 `01` 的切分依据 |

### Fusion And Review

```mermaid
flowchart LR
    A[四路候选] --> D{分歧 / 空识别 / 异常重复?}
    D -->|无| P[保留本方案主稿]
    D -->|有| R[收集并扩展争议窗口<br/>Qwen / FireRed / Whisper 三批并行复听]
    R --> U{仍未解决?}
    U -->|是| M[MOSS-Audio 再听原音]
    U -->|否| J[保守裁定]
    M --> J
    J --> P
    P --> T[标点校验 → 字词对齐 → speaker 归属]
```

每个复核模型内部逐窗串行，先处理整批窗口，再集中对齐到原窗口范围；三个模型批次
彼此并行。三批全部结束后，仍不一致的窗口才交给 MOSS-Audio；两份融合稿共享复核响应，
各自以自己的主稿裁定。

| 质量约束 | 行为 |
| --- | --- |
| 文字替换 | 主模型复听也改口且有独立家族支持才考虑替换；数字、热词、专名启发式和多人活动窗口受保护 |
| 证据不足 | 保留主稿和待核对标记；多个同家族响应不增加独立票数 |
| 时间戳 | 全部还原为原录音整数毫秒；无效字词时间用 `null`，不平均摊分 |
| Speaker | 可多人或未知；联合窗口映射有歧义时保持未知，不凭相同标签合并身份 |
| 标点 | 仅允许标点变化；不得改写数字、大小写、空格和口语内容 |
| 联合输出 | 截断、结构错误、越界或明显漏尾须缩窗重试；无法安全对齐边界则报失败 |

多模型用于保留不同路线和发现分歧；一致、流畅或对齐成功都不能证明识别正确。

## Model Call Pipeline

```mermaid
flowchart LR
    R[音频 / 文本 / 有效参数] --> C{请求内响应已存在?}
    C -->|是| O[返回结果]
    C -->|否| L[等待本模型请求锁]
    L --> C2{等待期间已有结果?}
    C2 -->|是| O
    C2 -->|否| I[client.infer<br/>调用已驻留模型]
    I --> V[校验协议 / 完成状态<br/>响应只存请求内存]
    V --> O
```

同一请求按模型、切片路径与有效参数复用响应。请求间只共享驻留模型，不复用识别
结果。不同模型可并行调用，同一模型保持一个在途请求。模型原始响应在 HTTP 响应的
`evidence` 中只出现一次，
由 CLI 写入 `evidence.json`。

## Output And Usage

```text
texts/<录音相对路径与文件名>/
├── 01-qwen-fusion.md / .json
├── 02-firered-fusion.md / .json
├── 03-moss-td.md / .json
├── 04-vibevoice.md / .json
├── 05-qwen-nemotron.md / .json
├── index.md                  # 各方案完成情况与链接，不做排名
├── evidence.json             # 一份共享原始响应、复核依据和请求参数
└── trace.json                # phase / 模型调用、GPU、排队与耗时工程指标
```

这些文件完全由 CLI 从 server 的结构化响应生成。Markdown 展示原话、时间、speaker 与
待核对标记；JSON 保留候选、裁定和失败说明，并由 CLI 添加 `evidence` 字段引用共享证据。
复制单份 JSON 时一并携带 `evidence.json`。

普通话识别的质量检查保留：某个方案的模型失败时，该稿记录失败，其余可完成稿仍
一起返回；解码、公共 speaker 等前置环节失败则本次 HTTP 请求失败。CLI 仅在完整接收并
成功生成全部文件后发布结果目录，不保存任务状态。请求中断后重新执行；已有结果用
`--overwrite` 重新转录并覆盖。`/data/asr` 只需提供临时音频空间，不需要持久任务卷。

响应中的 `trace` 使用相对请求起点的毫秒时间，记录 upload / decode / prepare / first pass /
review / 五方案 phase，以及每次实际模型调用或 request cache 命中；CLI 将其原样写成
`trace.json`。模型事件记录固定 GPU identity、模型锁等待、CPU 排队和推理耗时，只保存输入
大小与输出数量摘要，不重复 `evidence` 中的正文和原始响应。

```bash
uv run platform/container/services/asr/client/asr.py ./recordings \
  --server http://asr-host:8080 \
  --out ./texts \
  --parallel 2
```
