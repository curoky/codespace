# ASR Maintenance

本目录维护普通话长录音转写 Service。面向系统使用者的架构、请求流程、持久数据与输出合同见
[DESIGN.md](DESIGN.md)；本文件只规定实现 ownership、不可破坏的行为和验证方法。质量语料与
最新实测基线见 [regression/AGENTS.md](regression/AGENTS.md)。

## Source Of Truth

| 领域 | Source of truth |
| --- | --- |
| 模型能力、显存预算、时长与并发 | `models/catalog.py` |
| 实例、端口、placement 与切窗 | `server/server.yaml` |
| 模型 revision 与下载 allowlist | `models/<model>/download_model.sh` |
| Python 与依赖 | 各目录 `.python-version`、`pyproject.toml`、`uv.lock` |
| 模型运行环境与启动参数 | `models/<model>/run`、必要时同目录 `serve.py` |
| 模型内部 HTTP 服务 | `models/<model>/service.py` 或上游 model server |
| 模型调用协议 | `models/<model>/client.py`；vLLM 公共协议在 `models/vllm.py` |
| HTTP API 与五方案编排 | `server/api.py`、`transcribe.py`、`recipes.py`、`transcript.py` |
| GPU 映射与 s6 控制 | `ops/`、`rootfs/etc/s6/s6-rc.d/` |
| image 与模型环境安装 | `Dockerfile`、`install-model-environments.sh`、`rootfs/` |
| 回归 corpus 与结果 | `regression/manifest.yaml`、committed `results/`、`metrics.json` |
| 正常部署输入 | repository root 的 `config.example.yaml` |

版本、端口、revision、placement 和模型参数以实现文件为准；`DESIGN.md` 的汇总表用于快速
审阅部署全貌，修改 source of truth 时必须同步更新，不能反向从文档驱动实现。

## Scope

只维护五套固定方案所需的模型与静态实例。不要增加任意模型组合、动态 s6 definition、通用
worker、持久任务队列、任务状态、轮询、幂等键、跨请求结果缓存或运行期模型迁移。Server 保持
单进程；所有模型在公开 `/health` ready 前完成启动，不用 lazy ready 把启动成本转移给首请求。

五套 recipe、HTTP schema、placement、模型参数和质量合同属于外部行为。结构重构必须先用测试
钉住这些行为，不以兼容层、旧路径或 feature flag 保留过渡形态。

## Model Runtime Contracts

- `models/<model>/` 是独立部署单元，完整拥有 revision、environment、依赖、启动命令、内部
  endpoint、client adapter，以及需要时的 HTTP service。阅读或修改一个模型的部署不需要追踪
  catalog 分支、共享 shell 或 service factory；模型间只共享顶层 `protocol.py` 数据合同。
- 每个 `run` 显式声明本模型的 cache、offline、CPU/JIT 和 model server 配置，不 source 其他
  模型部署脚本。少量环境变量重复是部署边界的一部分，不为消除这些重复增加模板或生成器。
- `run` 和 `download_model.sh` 使用 `uv run --frozen --no-sync`。容器启动和手动下载都不得
  解析、安装或更新依赖。
- `weights` 是指向 `/model-data/<model>` 的固定 symlink。下载脚本使用固定 repo、revision 和
  显式 include，成功后写 `.revision`；marker 匹配时不访问 Hugging Face。
- 每个 `client.py` 实现相同的 typed callable，并在本目录固定 endpoint、serialization、timeout
  和模型特有参数。Scheduler 只加载该接口，不理解具体模型协议。
- SDK 模型的 `service.py` 明确声明 health、endpoint、单在途锁、`/data/asr` 文件边界、checkpoint
  加载和推理。SDK 中的 `cuda:0` 指进程可见的第一张卡。
- vLLM transcription 通过 `models/vllm.py` 统一 multipart、SSE 完整性和生成重试。响应必须
  收到 `[DONE]` 且所有 finish reason 为 `stop`；截断或不完整响应失败。
- 正常生成保持模型原始 greedy 参数。确认至少 64 字符的 1–8 字符短周期重复后，依次用
  repetition penalty 1.1、1.2、1.3 重试；仍重复或明确到达 length 后，使用固定 seed 的轻采样。
  成功重试的实际参数和 warning 必须进入 evidence。
- VibeVoice 沿用上游 transcription request，并传真实 WAV 时长。固定 chat template、上下文预算、
  输出解析与 data URL 是一个协议单元。
- 不修改 site-packages。确需修复第三方运行时行为时，在本目录的 launcher 或 wrapper 中建立
  稳定、可测试的边界。

## Pipeline Invariants

- `api.py` 只接收完整文件并返回五份结果、共享 evidence 与 trace。Markdown、索引和离线
  `trace.html` 由 CLI 生成并原子发布。
- prepare 先做全文件 speaker diarization，再将 speaker activity 与 VAD 取并集。四路 first
  pass 处理相同短窗，候选之间不能互喂答案。
- review 只处理分歧、空识别或异常重复窗口。Qwen、FireRed、Whisper、MOSS-Audio 各自形成
  独立批次；MOSS-Audio 是 speculative review，只有三路主复听仍不一致时才进入证据。
- 多人窗口禁止融合替换，joint recipes 也不消费 review 文本，因此不得为多人窗口执行无效
  review。Qwen 和 FireRed 两份融合稿独立裁定，不能读取对方定稿。
- FireRedPunc 是最终句读唯一 owner。送入前去除 Unicode punctuation，只保留数字内部的小数点、
  千分位逗号和时间冒号；模型若改写非标点正文则拒绝结果。
- 03 MOSS-TD 与 04 VibeVoice 保留自己的正文、时间和 local speaker。Pyannote 只映射无歧义的
  全文件身份。失败窗口先去 padding，再按 exact core 安全二分；不得猜测裁剪、平均插值或伪造
  时间。仅跨 core 边界且确需裁正文时调用 Aligner。
- 05 完整复用 01 正文与字词时间，只用 Nemotron 重标 speaker。已知超过八人时失败，未知人数
  标记未验证。
- 请求内以逻辑模型、切片和有效参数 cache 并 single-flight；失败不缓存，取消必须释放实例。
  请求间只共享常驻进程，不共享识别结果。
- 原始响应与参数只在 evidence 保存一次。trace 不复制正文，记录 phase、实际模型调用、cache
  hit、GPU identity、模型锁、CPU 排队、推理时间和 GPU 原始采样。

## Placement And Process Control

`server/server.yaml` 只使用容器可见 GPU 的逻辑序号。`scheduler.py` 在 startup 将逻辑序号映射
为 GPU UUID，检查静态显存预算与空闲设备，写入实例环境后用一次 s6 transaction 启动全部实例，
并发等待 health。请求失败不启停或迁移模型；模型异常退出由 s6 supervision 负责重启。

并发 slot 必须同时匹配 catalog 与模型 server 的 batch capacity。实例池按配置顺序选择首个可用
slot；VibeVoice A 优先承担同卡 continuous batching，B 只承接溢出。placement 关注 critical
path 和 phase 隔离，不以八卡平均利用率相等为目标。

FireRed TP2 使用固定 KV cache，关闭 startup plan、custom all-reduce 和 FlashInfer all-reduce，
TP 通信走 NCCL。修改 TP、精度、显存比例、上下文、max sequences、时长或 placement 时，必须
同步 catalog、server config、deployment tests，并重新跑冷/热启动与九音频回归。

模型停止由 s6 发 TERM，超时后终止进程组；`finish` 清理 engine 子进程。独立排查模型前先停
容器服务，不在运行中的 server 外改变 s6 状态。

## Image And Filesystem

模型权重不进入 image。`install-model-environments.sh` 在一个 layer 内安装隔离 `.venv`，再用
hardlink 做内容级去重；任一 lock、安装或去重失败都必须使 build 失败。模型环境不能为统一版本
而混装 Torch、torchaudio 或 SDK。

运行身份固定为非 root 用户 `x`。模型权重、request workspace 和 compilation cache 使用部署
声明的持久目录；Hugging Face token 只能来自 Podman secret。真实 token、Host 配置、模型 cache
和回归音频 cache 不得提交。

| s6 / filesystem 资产 | 维护约束 |
| --- | --- |
| `asr-<model>-download/` | oneshot；marker 命中立即完成，否则下载固定 snapshot |
| `asr-<instance>/` | longrun；显式依赖对应 download oneshot，以 x 运行 |
| `asr-server/` | 以 x 运行 `server/run`；只有它进入 default bundle |
| `/usr/local/bin/asr-model-service` | root-owned 固定 start / stop 入口 |
| `/var/log/s6.asr-*.log` | 使用 shared s6 runtime 的日志约定 |
| `/model-data` | 正常部署 rw；x 必须可写；禁止挂载 `/opt/asr` 或模型目录遮蔽代码与 venv |
| `/data/asr` | x 可写的请求临时区，不保存转录结果或任务状态 |
| `/home/x/.cache` | x 可写的持久 runtime cache，只保存可再生编译与 serving cache |

## Validation

Python 改动按以下顺序检查：

```bash
uv run --project platform/container/services/asr/server \
  ruff format --check platform/container/services/asr
uv run --project platform/container/services/asr/server \
  ruff check platform/container/services/asr
MYPYPATH=platform/container/services/asr \
uv run --project platform/container/services/asr/server \
  mypy --strict \
  platform/container/services/asr/server \
  platform/container/services/asr/ops \
  platform/container/services/asr/protocol.py \
  platform/container/services/asr/client/asr.py \
  platform/container/services/asr/models/catalog.py \
  platform/container/services/asr/models/vllm.py
uv run --project platform/container/services/asr/server \
  pytest -c platform/container/services/asr/server/pyproject.toml \
  platform/container/services/asr/tests
```

行为或 artifact 变更还必须运行：

```bash
task check:full
podman build --file platform/container/services/asr/Dockerfile \
  --tag localhost/codespace-asr:test .
```

| 修改 | 附加验证 |
| --- | --- |
| `run` / `client.py` / HTTP stack / s6 | 固定端口匹配；SSE 完整性；以 x 启动；health、真实短音频与停止后进程退出 |
| download / uv / Dockerfile | image 无权重且包含全部环境；run / download 不 sync；检查 hardlink 去重与最新 image size |
| 权重 / SDK / vLLM | 锁文件与 import 版本、实际协议响应、截断、时间边界与 `DESIGN.md` model table |
| 融合 / speaker / 时间 | 行为测试与对应真实音频，不能以模拟响应宣称质量提升 |
| regression corpus / baseline | `prepare.py --check`、`evaluate.py`、fixture tests；audio cache 不提交，raw results 提交 |
| CUDA / placement | 八卡同时驻留、真实余量、kernel、TP / NCCL 与跨模型并发；不停止外部任务 |

真实验证使用 `test-asr` skill：确认八张 GPU 空闲、挂载持久 model-data/cache、注入 HF secret，
等待 15 个实例 ready 后运行真实音频。回归按
[regression/AGENTS.md](regression/AGENTS.md) 的固定命令刷新九项结果并重算指标。结束时正常停止
容器，并确认 GPU 0–7 显存均回到 0 MiB。
