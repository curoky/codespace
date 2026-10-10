# ASR Maintenance

本目录是普通话完整录音转写服务。面向使用者和架构评审的启动、请求、挂载、模型、GPU 与
image 视图统一放在 [DESIGN.md](DESIGN.md)；本文件只保留实现维护约束、版本组合、更新方法
与验证证据。模型特有参数的原因和协议坑写在对应代码旁，不新增每模型说明文件。

## Context And Ownership

| 修改内容 | Source of truth / 必须同步检查 |
| --- | --- |
| 产品边界、启动与请求流程、挂载、模型清单、GPU / image 视图 | `DESIGN.md` |
| 模型启动参数与监听端口 | `models/<model>/run`；SDK 参数在同目录 `service.py` |
| 权重来源、格式与体积 | `models/<model>/download_model.sh` 的 repo、revision、include；体积变化同步 `DESIGN.md` |
| Python 与依赖版本 | 每目录 `.python-version`、`pyproject.toml`、`uv.lock` |
| 模型请求协议 | `models/<model>/client.py` 的 `infer(http, url, request)` |
| 能力、时长与显存预算 | `models/catalog.py`；instance / port / placement 在 `server/server.yaml` |
| HTTP 边界与请求编排 | `server/api.py`、`transcribe.py`、`recipes.py`、`transcript.py` |
| 文件并发与本地产物 | `client/asr.py` |
| 长音频回归语料、标准答案、实测结果与质量指标 | `regression/AGENTS.md`、`regression/manifest.yaml` |
| GPU 映射、s6 状态切换与进程退出 | `ops/`、`rootfs/etc/s6/s6-rc.d/` |
| image、用户、目录与环境安装 | `Dockerfile`、`install-model-environments.sh`、`rootfs/` |
| 正常部署输入 | repository root 的 `config.example.yaml` |

只维护五方案实际使用的模型。不要增加通用 worker、任意模型组合、参数 launcher、环境准备
job、动态 s6 definition、持久任务队列、任务状态、轮询、幂等键、恢复或跨请求缓存。配置
使用 YAML；uv 工具文件除外。版本、端口、revision 与参数的实际值始终以代码和 lock 为准。

## Runtime And Serving Maintenance

server 使用 Python 3.14.7；模型环境彼此隔离，不能为了统一版本混装 Torch、torchaudio 或
SDK。逐模型的 Python、SDK、Transformers、vLLM、Torch、CUDA、Serving 和存储体积只维护
在 `DESIGN.md` 的模型汇总表；实际 source of truth 仍是各目录 `.python-version`、
`pyproject.toml` 与 `uv.lock`。升级依赖后必须从 lock 的 Linux 解析结果更新该表。

Server 内部模型调用使用 Pydantic 团队维护的 `httpx2`，vLLM client 通过原生
`AsyncClient.sse()` 解析 Server-Sent Events；`models/vllm.py` 只负责 OpenAI completion
schema 与完整性判断。独立 CLI 仍用 HTTPX 普通 JSON API，并用 Pydantic 校验完整响应。
升级任一 HTTP stack 时同时跑 protocol、client 与完整模拟 pipeline 测试。

升级 serving 时重新核对 model class、endpoint 与 response schema。Qwen 普通 / `-hf`、
VibeVoice 原版 / HF、FireRed 原始 / 转换权重不能互换；FunASR 的 `paraformer-zh` 简称在
不同 hub 指向不同仓库。

## Model Contracts

- `run` 与 `download_model.sh` 一律使用 `uv run --frozen --no-sync`，只运行 image 已安装的
  环境；container startup 与手动下载都不能解析、安装或更新依赖。
- 每个 `weights` 是 image 内固定 symlink，目标为 `/model-data/<model>`。下载脚本先创建
  symlink 实际目标，再用固定 repo、revision 和显式 include 调 HF CLI；不下载其他框架或
  精度副本。成功后写 `.revision`，marker 匹配时不访问 Hugging Face。
- 监听端口与实例 placement 由 `server/server.yaml` 固定；scheduler 向 s6 写入 `PORT` 与
  `CUDA_VISIBLE_DEVICES`，并把实例 URL 传给 client。端口变化还要更新 `DESIGN.md` 的模型表。
- vLLM transcription 的 `SpeechToTextConfig` 由 model class 从 processor 构造，`run` 不传
  server 级覆盖。普通 ASR 上层限制为 30 秒，联合模型按 catalog 上限切窗。
- VibeVoice 必须沿用上游 transcription request。vLLM 不替换 checkpoint template 中的
  `<|AUDIO_DURATION|>`，因此固定 chat template，并由 client 传真实 WAV 时长；audio data
  URL、输出字段、生成预算与总上下文预算必须成套维护。
- FireRed 中文请求必须显式传 `language=zh`；Whisper 固定中文 transcription。所有 vLLM
  流都必须收到 `[DONE]` 且 finish reason 全为 `stop`，长度截断一律失败。正常调用保持模型
  原始 greedy 参数；只有流式输出确认进入至少 64 字符、周期 1–8、重复至少 8 次的短周期
  循环后，才依次用 repetition penalty 1.1 / 1.2 / 1.3 重试；三档仍循环时再使用固定
  `temperature=0.5`、`top_p=0.9`、`seed=2` 轻采样。明确到达 length 上限时直接使用同一组
  轻采样参数重试；成功响应必须在 evidence 记录实际参数与 retry warning，重试后仍不完整
  则失败。
- SDK 服务只接受 `/data/asr` 内真实文件；vLLM client 发送音频内容。SDK 中的 `cuda:0`
  表示当前进程可见的第一张卡，不是 Host 物理卡 0。
- 修改 tensor parallel、精度、显存比例、上下文或模型时长后，同步 `models/catalog.py`、
  `server/server.yaml`、deployment test，以及 `DESIGN.md` 的模型 / GPU 表。

### Storage Measurement

`DESIGN.md` 的 checkpoint 大小按每个下载脚本固定 revision 的 repository metadata 统计，
只计 serving 实际 include 的 weight；config、tokenizer、词典、CMVN 与 download cache 不
计入 checkpoint，不可拆分的 `.nemo`、`.pth.tar` 按整文件计。完整 model-data 另计 allowlist
内全部文件，但不计 HF metadata。

`.venv` 逻辑大小对每个目录执行
`du --apparent-size --block-size=1 --summarize`。共享 hardlink 会在每行完整计数，行值不能
相加代表 image 物理占用。image 总量与 layer 分布以完成构建后的 `podman image inspect` 和
`podman history --human=false` 为准；修改 revision、include、Python、lock、toolkit 或安装
去重流程后重新测量，并同步 `DESIGN.md`。

## Pipeline Invariants

- `api.py` 只收完整文件并返回五份结果、共享 evidence 与 trace；server 不生成 ZIP、
  Markdown、索引、可视化或客户端文件名。`client/asr.py` 严格校验 JSON，在临时目录生成
  全部文件后原子发布，并给五份方案 JSON 添加 `evidence.json` 引用。`client/trace.html`
  是无外部依赖的离线模板，流程聚合、方案对比、时间线、火焰图和 Chrome Trace export
  GPU 利用率曲线、流程聚合、方案对比、时间线、火焰图和 Chrome Trace export 全部在浏览器
  执行；`trace.json` 仍是唯一原始 trace 产物。Server 只按秒采集自身 placement 使用的 GPU
  compute / HBM I/O busy、显存与功耗原始值，不生成聚合结论或展示层。
- Server 必须单进程，不增加 uvicorn workers。上传与 options 是不可信 HTTP 输入，由
  Pydantic 校验；模型完成状态、结构、截断和时间边界也在 server 校验。
- 顺序固定为 prepare、四路 first pass、整批 review，随后 01–04 并行；05 只等待 01。prepare 先跑全文件
  pyannote，再取 speaker 与 VAD 活动并集；短窗与 padding 在所有候选间保持相同。
- first pass 的四个模型并行处理各自完整批次，同模型逐窗串行。候选不能互喂答案。只对
  分歧、空识别或异常重复扩窗复听；Qwen / FireRed / Whisper 三批并行，全部结束后才决定
  是否调用 MOSS-Audio。
- FireRedPunc 是最终句读的唯一 owner。送入标点模型前删除全部 Unicode punctuation，只保留
  数字内部的小数点、千分位逗号和时间冒号；输出改变非标点内容时拒绝。不在正文与标点层
  叠加句读，也不用重复标点正则修补模型输出。
- 整窗复听替换要求主模型改变且独立家族精确支持，窗口不能含敏感内容。Qwen 才允许局部
  edit-span：左右各至少四个稳定 content-character 锚点，且同一 edit 必须由两个独立模型家族
  在首轮候选或复听中精确支持。数值、热词和英文专名只保护各自 span，多人窗口仍整窗禁止
  替换；同家族和重复采样不增加独立票数，两份融合稿不能读取对方定稿。
- 联合模型保留自身正文、时间与局部 speaker；pyannote 只把无歧义的单人活动映射到全文件
  身份。结构、时间范围与活动尾部要校验，失败最多缩窗三层；无法按字词时间安全裁剪边界
  时先用无 padding 的 exact core 最后重跑，不做猜测裁剪、平均插值或伪造时间；exact core
  仍失败才使方案失败。完全位于 core 内的 segment 直接保留联合模型时间与 mapped speaker，
  只有跨 core 边界、确实需要裁剪正文时才调用 Aligner。
- forced alignment 的零时长 token 保留原始时间点，按落入的半开 speaker span 归属身份；
  不得为规避 `speaker_unknown` 人工扩展 token 时长或伪造边界。
- 第五稿复用第一稿正文和时间，仅用 Nemotron 重标 speaker。已知超过 8 人时失败，未知
  人数标 `unverified_max_8`，pyannote 观察超限标 `suspected_out_of_scope`。
- 同一请求按逻辑模型、切片路径与有效参数缓存并 single-flight；失败调用不缓存，取消
  必须释放实例。请求间只共享常驻进程，不共享识别结果。
- Aligner review 固定走 `qwen3-aligner-review`，recipe finalize 固定走
  `qwen3-aligner-recipe`。VibeVoice 长窗并发投递到 A / B 副本，必须按原窗口顺序合并。
- 原始响应与参数只在 evidence 出现一次。trace 记录关键 phase、实际模型调用、cache hit、
  GPU UUID / index、模型锁、CPU 排队、推理时间，以及请求全程每秒 GPU 利用率采样；不复制
  正文或完整部署清单。`utilization.memory` 表示 HBM 读写活跃时间，不得解释为显存占用率或
  PCIe copy throughput。

## Static Placement And Process Control

`server/server.yaml` 按实例声明逻辑模型、端口与可见 GPU 序号。当前每卡预算和并发隔离见
`DESIGN.md`；deployment test 必须离线校验模型集合、TP 卡数、单卡总量、并发阶段不共卡与
vLLM 显存比例。placement 不能写 Host 物理卡号。

`scheduler.py` 在 lifespan startup 时把逻辑序号映射为 GPU UUID，要求已使用显存不超过
512 MiB，再依次启动全部实例并等待 health。请求期每实例最多一个在途调用，
逻辑模型池选择当前空闲副本；不启停、回收、迁移或降级模型。

`ops/processes.py` 负责有超时的子进程与 GPU inventory，并以 x 经 sudo 调 root-owned
`/usr/local/bin/asr-model-service`。sudoers 只授权该固定入口；shared s6 live state 仍由
root 管理。模型异常退出由 s6 supervision 重启；HTTP 请求失败不能触发停服。

停止由 s6 发 TERM，`timeout-kill` 与 `flag-timeout-killpg` 超时终止进程组；`finish` 以 x
清理残留 engine 子进程。容器 shutdown 时 server 不再次逐模型 stop。独立排查模型前先停
容器服务，不在运行中的 server 外手动改变 s6 状态。

## Image, S6 And Mount Constraints

`install-model-environments.sh` 必须在一个 image layer 中遍历全部模型，以
`UV_LINK_MODE=hardlink` 建独立 `.venv`。server 安装后用 util-linux `hardlink` 做第二遍
内容级去重；它只忽略 mtime，mode、owner 与 xattr 不同的文件不会合并。任一 lock 失配、
安装或去重失败都必须使 build 失败。Python / environment 安装阶段使用 `USER x`，清理 uv
cache 后才结束 layer；s6 graph 切回 root 编译。

| s6 / filesystem 资产 | 维护约束 |
| --- | --- |
| `asr-<model>-download/` | oneshot；marker 命中立即完成，否则下载固定 snapshot |
| `asr-<instance>/` | longrun；显式依赖逻辑模型 download oneshot，以 x 运行 |
| `asr-server/` | 以 x 运行 `server/run`；只有它进入 default bundle |
| `/usr/local/bin/asr-model-service` | root-owned 固定 start / stop 入口 |
| `/var/log/s6.asr-*.log` | 使用 `redirfd -w` 与 `fdmove`，沿用 shared runtime |
| `/model-data` | 正常部署 rw；x 必须可写；禁止挂载 `/opt/asr` 或模型目录遮蔽代码与 venv |
| `/data/asr` | x 可写的请求临时区，不保存转录结果或任务状态 |

HF token 只在 download oneshot 需要联网时从 `/run/secrets/huggingface_token` 读取；必须
以 UID/GID `5230:5230` 可读，不能进入命令行、脚本、image layer 或 model-data。marker
全部匹配时不能读取 token。FireRed TP / NCCL 要求 private `/dev/shm` 为 8 GiB，不能退回
Podman 默认 64 MiB，也不改用 host IPC。

## CUDA Forward Compatibility

Host driver 不能升级。H100 支持 CUDA forward compatibility；当前 image 为 R535 显式
提供 CUDA 13 compatibility userspace libraries 和全局 compiler toolkit。

- Dockerfile 固定 `cuda-compat-13-0` 包与 SHA256，只解压用户态库到
  `/usr/local/cuda-13.0/compat`，不修改 Host kernel module 或 ldconfig。
- GPU `run` 在 Python 前固定 `LD_LIBRARY_PATH`；vLLM 同时固定 `CUDA_HOME`，让 engine
  子进程继承 compat 与 JIT compiler。link-only driver stub 不进入 runtime library path。
- 不使用 `VLLM_ENABLE_CUDA_COMPATIBILITY` 代替上述 wiring；这里不是官方 vLLM image
  entrypoint。compat 只解决 driver interface，不解决 Torch、vLLM 或 extension 混装。
- 不根据旧 driver 动态选择 Torch backend 或降级 CUDA；以 lock、实际 import、kernel、
  Triton / vLLM extension、TP 与 NCCL 验证整套兼容性。

2026-10-07 在 H100 / R535 `535.161.08` 上，原生用户态 Driver API 为 12020，PTX 9.0 JIT
报错 222；compat 提供 Driver API 13000，并通过 VMM / POSIX FD、PTX 9.0 kernel 与 CUDA
Graph 探针。该结果只证明底层接口，不能替代完整模型推理。

## Alternatives Outside Scope

这些候选只保留为选型背景，不为它们创建依赖、配置或兼容入口：

| 环节 | 候选 | 未进入当前实现的原因 / 独立部署路径 |
| --- | --- | --- |
| ASR | FireRedASR2-AED | 官方 FireRed SDK，非当前 vLLM 转换权重 |
| ASR | Fun-ASR-Nano-2512 | vLLM、Omni 与 FunASR 使用不同 checkpoint 形态 |
| ASR | GLM-ASR-Nano-2512 | 官方 Transformers；虽有 vLLM / SGLang 路径，但不属于五方案 |
| 热词 ASR | SeACo-Paraformer | 独立 hotword checkpoint，不等于当前 Paraformer |
| VAD | TEN-VAD、FSMN-VAD、Silero | 当前固定 FireRedVAD，不保留替换开关 |
| 对齐 / 标点 | fa-zh、CT-Punc | 当前固定 Qwen aligner 与 FireRedPunc |
| Speaker embedding | CAM++ | embedding 不是完整 diarizer |

Qwen 0.6B、Whisper turbo、MOSS-Audio 其他尺寸与 Thinking 变体也不在当前产品边界。

## Validation

行为修改运行：

```bash
task check:full
```

image 或 runtime 依赖变化还必须从 repository root 构建：

```bash
podman build \
  --file platform/container/services/asr/Dockerfile \
  --tag localhost/codespace-asr:test \
  .
```

| 修改 | 附加验证 |
| --- | --- |
| `run` / `client.py` / HTTP stack / s6 | 固定端口匹配；SSE 完整性；以 x 启动；health、真实短音频与停止后进程退出 |
| download / uv / Dockerfile | image 无权重且包含全部环境；run / download 不 sync；检查两轮 hardlink 去重与最新 image size |
| 权重 / SDK / vLLM | 锁文件与 import 版本、实际协议响应、截断、时间边界与模型 table |
| 融合 / speaker / 时间 | 行为测试与对应真实音频，不能以模拟响应宣称质量提升 |
| regression corpus / baseline | `prepare.py --check`、`evaluate.py`、fixture tests；音频 cache 不提交，raw results 提交 |
| CUDA / placement | 五卡同时驻留、真实余量、kernel、TP / NCCL 与跨模型并发；其余可见卡空闲，不停止外部任务 |

已验证 CPU FireRedVAD / FireRedPunc、H100 Nemotron、s6 服务链路、异常退出清理、停止超时，
以及原子 HTTP 五方案模拟响应、共享 evidence 与临时音频清理。

2026-10-09 在 8×H100 80 GiB / R535 Host 上只使用前 5 卡完成 20:34 真实普通话音频：
15 个实例全部 ready，五份结果完成，客户端 139.32 秒，trace 138.263 秒；1626 次真实
模型调用、24 次 cache hit、0 failure。01–04 在 113.136–113.137 秒同时启动，05 在 01 结束的
129.123 秒启动，没有等待 02–04；VibeVoice A / B 各处理 4 个长窗，04 用时 25.007 秒。
请求前五卡占用为 64,654 / 29,920 / 51,648 / 49,154 / 45,518 MiB，请求后为
66,524 / 33,150 / 52,572 / 51,298 / 48,118 MiB，其余三卡为 0。无 OOM、shared-memory 错误或
模型重启；容器 exit 0 后八卡全部回到 0 MiB。这证明当前 placement 与并发时序在该 Host
可运行，不代表其他 GPU 容量、driver 或 revision。真实 GPU 验证必须遵循 repository 的
`test-asr` skill。

2026-10-09 在同一 Host 以新的 `audio_verbatim` 《狂人日记》参考做五卡质量复验：
01 / 05 的 CER 从局部融合前 2.6420% 降到 2.4938%，接受 10 个 local-consensus 窗口；
02 / 03 / 04 分别为 2.2222% / 2.9136% / 2.2716%。最终 trace 为 140.894 秒、1660 个事件、
1650 个模型事件和 0 failure，只使用 GPU index 0–4；01–04 在 112.935–112.937 秒启动，
05 在 01 完成的 123.764 秒启动。全量去标点输入后，真实文本中已无上游引号诱发的组合句读。

2026-10-10 用 schema v2 在同一 Host 复跑 meeting `R8004_M8006_MS805-first20m.wav`：
trace 为 1070.531 秒、863 个事件和 995 组请求全程 GPU 采样，sampling error 为空。GPU 0 / 1
平均 compute busy 为 96.2% / 81.9%，GPU 2 / 3 / 4 仅 5.4% / 3.6% / 1.8%；CPU queue
为 0，model queue 仅 0.318 秒，upload + decode 为 0.293 秒。89 次模型失败中 FireRed-LLM
有 67 次生成到 length 上限，失败调用累计 855.961 秒；MOSS-Audio、Qwen3-ASR 与 Whisper
另有 27 次 length failure，全部失败调用累计约 1023 秒。该样本的瓶颈是异常长生成把 GPU 0 / 1
打满，同时其他卡受 DAG 与静态 placement 限制长期空闲，不是 CPU 并发或输入 copy；降低耗时应
先修复生成长度与失败窗口，再评估跨卡并发，不能仅提高 `cpu_requests`。

同日应用异常生成重试和 joint exact-core 边界回退后，以同一 meeting 音频完成五卡复验：
五份方案全部 completed，trace 为 276.738 秒、2318 个事件、2308 个模型事件、2255 次非缓存
调用、53 次 cache hit 和 255 组 GPU 采样。保存到 evidence 的 358 个 completion finish reason
全部为 `stop`；短周期循环在 repetition penalty 1.1 / 1.2 / 1.3 下分别恢复 66 / 21 / 1 次，
另有 1 次 length 由固定采样恢复。trace 中保留 3 个被严格检测提前取消的 VibeVoice 内部失败
尝试，上层缩窗后 04 仍 completed，不应误报为零失败事件。CPU queue 仍为 0；model queue
为 16.383 秒，其中 Qwen Aligner 占 15.313 秒，来自 exact-core 安全对齐。GPU 0–4 平均
compute busy 为 53.5% / 37.8% / 33.9% / 30.9% / 22.7%，峰值均为 100%。相对修复前
1070.531 秒，端到端耗时下降 74.2%；剩余耗时主要在 review 与 joint 质量恢复 / 对齐，不是
CPU 或输入 copy。
