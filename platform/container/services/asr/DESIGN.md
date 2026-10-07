# Chinese Recording Transcription

把完整的普通话对话录音转成**带时间戳、说话人和待核对标记的原话记录**。
每个文件固定产出 **5 份 Markdown + 5 份 JSON + 1 份索引**，分别保留不同识别与
说话人方案的结果。中文为主，保留夹杂英文、语气词、重复和插话。

| 输入 | 处理 | 输出 | 部署 |
| --- | --- | --- | --- |
| 完整录音文件或目录 | VAD → 多模型识别与复核 → 标点 / 对齐 / speaker | 五套转录文档及证据 JSON | 一个 Linux 容器 + Python CLI |

不处理粤语、实时流、翻译、摘要或跨文件身份识别；不需要网页、数据库或外部队列。
维护入口是 [AGENTS.md](AGENTS.md)，模型参数的原因和约束直接写在实现旁的注释中。

## Architecture

```mermaid
flowchart LR
    CLI[Python CLI<br/>并行上传、轮询、下载]
    subgraph Container[单个 Linux 容器]
        API[HTTP server<br/>0.0.0.0:8080]
        Jobs[文件队列 / 五方案编排 / 结果缓存]
        Ops[ops<br/>GPU 分配与启停请求]
        S6[s6<br/>下载任务与服务监督]
        Client[每模型 client.py]
        Model[每模型服务<br/>127.0.0.1:8000–8012]
        Data[文件存储<br/>/data/asr]
        API --> Jobs
        Jobs --> Client
        Client -->|原生 HTTP 协议| Model
        Jobs --> Ops
        Ops -->|受限 Shell 入口| S6
        S6 -->|download_model.sh / run| Model
        Jobs --> Data
    end
    CLI <-->|HTTP| API
```

| 层次 | 拥有的职责 | 交互方式 |
| --- | --- | --- |
| 上层 `server/` | 文件任务、音频切片、五方案、文字选择、时间与身份、产物 | 调用模型 client，不导入模型 SDK |
| 底层 `models/<model>/` | 本模型权重、Python 环境、参数、服务与 HTTP 协议 | 官方支持时原生 vLLM；其余用官方 SDK |
| 运维 `ops/` + `rootfs/` | GPU 池、按需启停、进程监督、用户与日志 | ops 请求 s6 操作，s6 执行静态脚本 |

每模型一个实例、一个固定端口、一个独立 uv 环境。GPU 数量影响等待和并行度；
多个方案共享实例，不要求全部模型同时驻留，也不绑定物理卡号。

## Project Layout

```text
asr/
├── DESIGN.md                 # 架构与执行流程
├── AGENTS.md                 # 维护约定、框架兼容与验证边界
├── Dockerfile
├── protocol.py               # 请求、时间片与结果契约
├── client/asr.py              # 独立 Python CLI
├── server/
│   ├── run / server.yaml      # HTTP 入口 / 编排配置
│   ├── api.py / jobs.py       # 上传、文件队列与恢复
│   ├── audio.py / recipes.py  # 音频处理与五方案
│   └── inference.py / transcript.py / artifacts.py
├── models/
│   ├── catalog.py            # 模型能力、时长限制与资源预算
│   ├── vllm.py               # vLLM 响应完成状态解析
│   └── <model>/
│       ├── pyproject.toml / uv.lock / .python-version
│       ├── download_model.sh # 固定 repo / revision，运行时下载
│       ├── run               # 监听地址、端口及模型启动参数
│       ├── client.py         # 固定服务地址、请求与结果解析
│       ├── service.py        # 仅 SDK / 特殊 pooling 接口需要
│       └── .venv/ / weights/ # 运行时生成，不进入仓库或镜像
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
        B2 --> B3[复制代码与 rootfs<br/>安装 server 环境，编译 s6 graph]
    end
    subgraph Boot[容器启动]
        B3 --> I[s6 init / root supervision]
        I --> S[以 x 执行 server/run]
        S --> R[停止本容器遗留模型实例<br/>恢复未完成文件任务]
        R --> H[HTTP ready<br/>接收上传与查询]
    end
    subgraph Demand[首次请求某个模型]
        H --> A[ops 等待 / 分配 GPU<br/>CPU 模型不占 GPU]
        A --> D[s6 download oneshot<br/>以 x 执行 download_model.sh]
        D --> U[uv run 同步本目录 .venv<br/>hf download 固定 snapshot]
        U --> M[s6 longrun<br/>以 x 执行模型 run]
        M --> V[uv run 同步环境<br/>加载本地 weights，等待 health]
        V --> Q[执行模型请求]
    end
```

| 时机 | 实际行为 |
| --- | --- |
| 构建镜像 | 准备 server；不安装模型环境，不下载模型权重 |
| 首次启动模型 | `download → service`；两个脚本各自通过 `uv run --locked --no-dev` 准备环境 |
| 同一容器再次启停 | 已完成的 download job 不重跑；`run` 检查环境并加载本地权重 |
| 容器重建 | download job 重新执行，HF 根据持久化 snapshot metadata 复用权重 |
| 显存不足 | FIFO 等待；必要时停止本容器无在途请求的模型，确认退出后释放资源 |

s6 负责进程与依赖，ops 负责资源分配。模型固定使用 `/data/asr` 读取音频，GPU 服务
仅接收动态 `CUDA_VISIBLE_DEVICES`；端口、路径、精度等参数均在模型目录内维护。

## Request Pipeline

一个文件按下图执行；五套方案依次运行，共享已完成的计算。CLI 可以并发提交文件，
server 限制活跃文件数，每个模型串行处理请求。

```mermaid
flowchart TD
    C[CLI 上传完整文件] --> U[POST /jobs<br/>保存原音、参数与部署指纹，返回 job ID]
    U --> Q[文件队列]
    Q --> F[FFmpeg 解码<br/>mono 16 kHz PCM，保留原始时间轴]
    F --> P[pyannote 全文件 speaker<br/>FireRedVAD 活动与 speaker 活动取并集]
    P --> W[统一切短窗]
    W --> A[四路第一轮识别<br/>Qwen / FireRed / SenseVoice / Paraformer]
    A --> R1[01 Qwen 主稿融合]
    R1 --> R2[02 FireRed 主稿融合<br/>复用四路候选与复听响应]
    R2 --> R3[03 MOSS-TD 联合转录<br/>带重叠的长窗口]
    R3 --> R4[04 VibeVoice 联合转录<br/>带重叠的长窗口]
    R4 --> R5[05 复用 01 的文字与时间<br/>Nemotron 重新标注 speaker]
    R5 --> O[生成五套 Markdown / JSON、索引与 zip]
    O --> D[CLI 轮询状态并下载产物]
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
    D -->|有| R[扩展原音上下文<br/>Qwen + FireRed + Whisper 复听]
    R --> U{仍未解决?}
    U -->|是| M[MOSS-Audio 再听原音]
    U -->|否| J[保守裁定]
    M --> J
    J --> P
    P --> T[标点校验 → 字词对齐 → speaker 归属]
```

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
    R[音频 / 文本 / 有效参数] --> C{任务内响应缓存命中?}
    C -->|是| O[返回结果]
    C -->|否| A[等待本模型请求锁与资源]
    A --> S[必要时经 s6 启动<br/>请求 client.URL 的 health]
    S --> I[client.infer<br/>发送音频或容器内文件路径]
    I --> V[校验协议 / 完成状态<br/>保存成功响应与证据]
    V --> O
```

缓存同时受内容、有效参数、模型脚本与锁文件指纹约束。同一任务跨方案共享响应，
任务间只共享驻留实例。依赖模型失败时记录受影响方案；成功方案继续保留。

## Output And Recovery

```text
/data/asr/jobs/<job-id>/
├── input/original            # 原始文件
├── resolved.json             # 参数、模型来源与部署指纹
├── status.json               # 整体及每方案状态
├── work/                     # 解码、切片与响应缓存
├── artifacts/
│   ├── 01-qwen-fusion.md / .json
│   ├── 02-firered-fusion.md / .json
│   ├── 03-moss-td.md / .json
│   ├── 04-vibevoice.md / .json
│   ├── 05-qwen-nemotron.md / .json
│   └── index.md              # 状态和链接，不做模型排名
└── transcripts.zip
```

Markdown 展示原话、时间、speaker 与待核对标记；JSON 另存候选、原始响应、复核依据和
失败说明。状态区分完成、部分失败、全部失败；失败方案也有明确的失败产物。

CLI 保存 job ID，断开不取消任务，再次执行恢复轮询。server 重启恢复未完成任务；
部署指纹变化后要求重新提交。已完成产物独立于工作缓存。

```bash
uv run platform/container/services/asr/client/asr.py ./recordings \
  --server http://asr-host:8080 \
  --out ./texts \
  --parallel 2
```
