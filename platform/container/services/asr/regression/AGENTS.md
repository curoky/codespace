# ASR Regression Corpus

本目录拥有普通话长音频回归集、标准答案和可复现的服务输出。大音频只按
`manifest.yaml` 下载到各题材的 `audio/` cache，不进入 Git；各题材的 `results/` 是
2026-10-10 在 6×H100 上运行五套 recipe 得到的已提交 baseline，包含 JSON、Markdown、
`evidence.json`、`trace.json` 和离线 `trace.html`。

## Corpus And Baseline

指标单元格依次为 **CER / SA-CER / DER**，均为越低越好；`—` 表示该指标不适用，
`failed` 表示服务明确返回失败，错误原因保留在对应 recipe JSON 和 `index.md`。conversation
与 meeting 使用人工 gold transcript/timing。《狂人日记》使用人工核对的 `audio_verbatim` 参考：
保留底本正字法，只校正录音中可确认的四处增字与一处省字。其余 narration 仍是公版原文的
source-text CER，可能同时反映版本、增删句和朗读差异；两者都不能与 gold CER 直接横向比较。

| Fixture | 来源 / License | 类型 | 内容 summary | 时长 | 大小 | 01 Qwen fusion | 02 FireRed fusion | 03 MOSS-TD | 04 VibeVoice | 05 Qwen + Nemotron |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `conversation-weather` | [MagicData-RAMC dev@79d508c](https://huggingface.co/datasets/EaseZh/magicdata_ramc/tree/79d508c3c3de40a0db55135f78113a7dfe6066d2) / CC BY-NC-ND 4.0 | 双人自然对话；女 + 男；gold | 南北方天气、气候变暖、穿衣和生活体验 | 30:07.875 | 55.17 MiB | 7.83% / 9.44% / 10.60% | 7.80% / 8.84% / 10.60% | 7.79% / 7.80% / 10.60% | 9.26% / 9.26% / 10.60% | 7.86% / 20.52% / 21.83% |
| `conversation-education` | [MagicData-RAMC dev@79d508c](https://huggingface.co/datasets/EaseZh/magicdata_ramc/tree/79d508c3c3de40a0db55135f78113a7dfe6066d2) / CC BY-NC-ND 4.0 | 双人自然对话；女 + 男；gold | 学校经历、专业方向、课程和就业规划 | 32:18.350 | 59.15 MiB | 6.43% / 9.60% / 14.01% | 7.23% / 10.25% / 14.01% | 6.58% / 8.55% / 14.01% | 8.58% / 10.50% / 14.01% | 6.43% / 9.59% / 16.46% |
| `conversation-film` | [MagicData-RAMC dev@79d508c](https://huggingface.co/datasets/EaseZh/magicdata_ramc/tree/79d508c3c3de40a0db55135f78113a7dfe6066d2) / CC BY-NC-ND 4.0 | 双人自然对话；女 + 男；gold | 《哪吒之魔童降世》的剧情、票房和角色 | 30:58.400 | 56.71 MiB | 10.09% / 12.15% / 10.84% | 10.32% / 12.17% / 10.84% | 8.79% / 9.07% / 10.84% | 12.50% / 12.95% / 10.84% | 10.09% / 11.71% / 14.46% |
| `meeting-annual-event` | [AliMeeting test@cef2837](https://huggingface.co/datasets/ggfox00000/dia-alimeeting-test/tree/cef2837c4a1a0762074522c1bbbbb90eb4d1acf5) / CC BY-SA 4.0 | 四人远场会议；channel 0；gold | 年会日期、节目、抽奖和员工参与安排 | 20:00.000 | 36.62 MiB | 26.70% / 40.42% / 21.28% | 34.51% / 44.82% / 21.28% | 16.33% / 60.09% / 21.28% | 33.91% / 44.05% / 21.28% | 27.06% / 34.33% / 16.22% |
| `meeting-game-launch` | [AliMeeting test@cef2837](https://huggingface.co/datasets/ggfox00000/dia-alimeeting-test/tree/cef2837c4a1a0762074522c1bbbbb90eb4d1acf5) / CC BY-SA 4.0 | 四人远场会议；channel 0；gold | 手游目标用户、使用时长、奖励机制和卖点 | 20:00.000 | 36.62 MiB | 55.93% / 69.49% / 33.82% | 65.06% / 72.79% / 33.82% | 39.85% / 83.62% / 33.82% | 61.65% / 83.17% / 33.82% | 56.23% / 70.64% / 22.82% |
| `meeting-bike-sharing` | [AliMeeting test@cef2837](https://huggingface.co/datasets/ggfox00000/dia-alimeeting-test/tree/cef2837c4a1a0762074522c1bbbbb90eb4d1acf5) / CC BY-SA 4.0 | 三人远场会议；channel 0；gold | 共享单车停放、安全、损坏和城市治理 | 20:00.000 | 36.62 MiB | 15.03% / 19.12% / 10.89% | 32.34% / 36.10% / 10.89% | 12.39% / 21.46% / 10.89% | 24.81% / 49.11% / 10.89% | 15.17% / 17.60% / 14.66% |
| `narration-madmans-diary` | [LibriVox《呐喊》](https://archive.org/details/call_to_arms_jl_librivox) / Public Domain | 单人文学朗读；audio-verbatim | 鲁迅《狂人日记》 | 20:34.245 | 18.84 MiB | 2.49% / — / — | 2.22% / — / — | 2.89% / — / — | 2.25% / — / — | 2.49% / — / — |
| `narration-hometown` | [LibriVox《呐喊》](https://archive.org/details/call_to_arms_jl_librivox) / Public Domain | 单人文学朗读；source text | 鲁迅《故乡》 | 20:25.213 | 18.70 MiB | 2.15% / — / — | 1.84% / — / — | 2.97% / — / — | 3.04% / — / — | 2.15% / — / — |
| `narration-village-opera` | [LibriVox《呐喊》](https://archive.org/details/call_to_arms_jl_librivox) / Public Domain | 单人文学朗读；source text | 鲁迅《社戏》 | 22:20.920 | 20.46 MiB | 2.97% / — / — | 3.12% / — / — | 3.41% / — / — | 3.41% / — / — | 2.97% / — / — |

`metrics.json` 保存上述逐 fixture 指标、reference quality、character accuracy、编辑计数和按题材
聚合值。评估前删除圈号脚注 marker，避免 NFKC 把其折叠为虚假的数字正文。当前
baseline 使用 image `localhost/codespace-asr:review-parallelism`（image ID `6ed73e621356`），
与同一提交中的 ASR server code 配套。baseline 中 45/45 个 recipe completed；未来出现失败时仍应作为回归
结果保留，不得删除、用其他 recipe 补值或把缺失指标记为 0。

## 2026-10-11 Startup And Execution Regression

本轮在同一台 8×H100 80 GiB / R535 `535.161.08` Host 上用 commit
`c40129c5ea055fd9938c8c5271ebc15f0046e52c` 和从该工作树构建的 image
`ce5d1f2050e3c19e1e7ea0c112b0f1ac25a81f0ae7af1e2370dc1a196c6dd830`（12.37 GB，
Podman 5.8.7）完成两轮速度回归。冷轮开始前 `/workspace/asr-model-data` 与
`/workspace/asr-cache` 均为空；热轮正常停止冷容器并确认八卡显存归零后，复用冷轮生成的
77 GB model-data 和 271 MB runtime cache，重新创建全部 15 个模型进程。两轮使用同一 image、
placement、音频顺序、`--parallel 1` 和 client 参数；回归输出写在仓库外，没有覆盖本目录的质量
baseline。

计时 `t0` 位于发起 `podman run` 之前。下载完成以固定 revision 的 `.revision` marker 首次出现为准，
内部实例 ready 以对应 health endpoint 首次成功为准，总 ready 以公开 `/health` 首次成功为准。
marker 约每 0.25 秒轮询一次，endpoint 约每秒轮询一次，因此这些时间是 wall-clock 观测值，不是函数级
profiler 数据。执行耗时以 server `trace.duration_ms` 为主，client wall time 包含 `uv` 启动、上传、
响应校验和本地产物生成。

### Startup Summary

| 阶段 | 冷启动 | 热启动 | 结果 |
| --- | ---: | ---: | ---: |
| `podman run` 返回 / container running | 35.720 s | 0.451 s | -35.269 s |
| 13 个 revision marker 全部完成 | 526.050 s | 启动前已存在；+0.482 s 首次轮询确认 | 冷轮并发下载长尾为 container running 后 490.330 s；热轮 download log 全为空 |
| 最后 marker 到公开 health ready | 172.522 s | 不适用 | 冷轮剩余长尾为模型加载、profile、compile、CUDA Graph 与 warmup |
| 15/15 实例及公开 health ready | **698.572 s** | **88.604 s** | **-609.968 s / -87.32%** |
| 正常停止 | 7.093 s | 7.088 s | 两轮停止后八卡均为 0 MiB |

冷轮 ready 时 GPU 0–7 分别占用 32,808 / 34,686 / 31,769 / 42,727 / 8,925 /
39,288 / 40,672 / 8,383 MiB；热轮为 39,652 / 34,686 / 31,203 / 43,503 / 9,923 /
40,774 / 40,672 / 7,959 MiB。两轮全过程均使用八卡，没有 OOM、模型进程重启或 shared-memory
错误。

冷轮的 13 个下载 oneshot 并发执行；下表不是可相加的串行耗时。`t0` 时间包含首次创建大 image
container rootfs 的 35.720 秒，后一列扣除了这段开销，更接近实际模型获取长尾：

| 模型 | `.revision` 完成（自 `t0`） | container running 后 |
| --- | ---: | ---: |
| FireRedVAD | 91.867 s | 56.147 s |
| MOSS-TD | 100.908 s | 65.188 s |
| Qwen3 ForcedAligner | 102.018 s | 66.298 s |
| MOSS-Audio | 108.652 s | 72.932 s |
| Nemotron Diarization | 221.687 s | 185.967 s |
| Paraformer | 223.455 s | 187.735 s |
| VibeVoice | 296.385 s | 260.665 s |
| SenseVoice | 338.970 s | 303.250 s |
| FireRedPunc | 394.777 s | 359.057 s |
| Pyannote Community-1 | 423.126 s | 387.406 s |
| Whisper Large V3 | 458.075 s | 422.355 s |
| Qwen3-ASR 1.7B | 459.452 s | 423.732 s |
| FireRed LLM | 526.050 s | 490.330 s |

下表的“冷初始化”是 marker 完成到该 endpoint ready 的 wall time，包含并发启动竞争；“热 ready”
是从热轮 `t0` 到 endpoint ready 的完整时间。相同 checkpoint 的两个副本共享 marker，但分别探测
endpoint：

| 实例 | 冷 marker | 冷初始化 | 冷 ready | 热 ready |
| --- | ---: | ---: | ---: | ---: |
| FireRedVAD | 91.867 s | 8.482 s | 100.349 s | 11.222 s |
| Qwen Aligner review | 102.018 s | 43.554 s | 145.572 s | 37.446 s |
| Qwen Aligner recipe | 102.018 s | 43.554 s | 145.572 s | 37.446 s |
| Nemotron Diarization | 221.687 s | 19.661 s | 241.348 s | 21.952 s |
| Paraformer | 223.455 s | 17.893 s | 241.348 s | 20.722 s |
| MOSS-Audio | 108.652 s | 165.657 s | 274.309 s | 58.923 s |
| MOSS-TD | 100.908 s | 175.623 s | 276.531 s | 70.683 s |
| SenseVoice | 338.970 s | 16.790 s | 355.760 s | 19.532 s |
| FireRedPunc | 394.777 s | 8.812 s | 403.589 s | 11.222 s |
| Pyannote Community-1 | 423.126 s | 13.209 s | 436.335 s | 17.157 s |
| VibeVoice A | 296.385 s | 168.209 s | 464.594 s | 88.324 s |
| VibeVoice B | 296.385 s | 168.209 s | 464.594 s | 88.324 s |
| Whisper Large V3 | 458.075 s | 140.560 s | 598.635 s | 50.621 s |
| Qwen3-ASR 1.7B | 459.452 s | 165.078 s | 624.530 s | 56.556 s |
| FireRed LLM | 526.050 s | 172.242 s | 698.292 s | 83.638 s |

vLLM 自身日志把权重加载、`torch.compile`、CUDA Graph 和 engine init 分别量化如下。`engine init`
指日志中的 profile、KV cache 创建和 model warmup，已经包含同一行报告的 compilation 以及 Graph
capture，不能与其他列相加。Graph 中的 `+` 表示日志明确记录的多次 capture；FireRed TP2 的
`/` 表示两个 rank。Qwen Aligner 固定 eager，compile、Graph 与 JIT kernel warmup 均禁用：

| 实例 | 权重加载 冷 → 热 | `torch.compile` 冷 → 热 | CUDA Graph 冷 → 热 | engine init 冷 → 热 |
| --- | ---: | ---: | ---: | ---: |
| FireRed LLM TP2 | 5.990 / 6.601 → 6.458 / 6.589 s | 13.25 → 0.28 s | 10 / 10 → 9 / 9 s | 105.94 → 19.48 s |
| MOSS-Audio | 8.606 → 10.030 s | 29.14 → 0.68 s | 5 + 6 → 7 s | 118.68 → 15.94 s |
| MOSS-TD | 4.848 → 5.320 s | 26.96 → 0.84 s | 3 + 5 → 5 s | 120.30 → 18.17 s |
| Qwen Aligner review | 4.967 → 5.053 s | disabled | disabled | 4.09 → 3.63 s |
| Qwen Aligner recipe | 4.899 → 5.041 s | disabled | disabled | 4.15 → 3.17 s |
| Qwen3-ASR 1.7B | 5.295 → 5.451 s | 27.86 → 0.41 s | 4 + 5 → 5 s | 116.24 → 12.80 s |
| VibeVoice A | 9.196 → 9.525 s | 15.80 → 8.20 s | 5 + 6 → 4 + 5 s | 109.75 → 33.14 s |
| VibeVoice B | 9.556 → 9.419 s | 15.11 → 8.42 s | 4 + 6 → 4 + 6 s | 109.21 → 33.48 s |
| Whisper Large V3 | 4.956 → 5.322 s | 9.67 → 0.32 s | 1 + 4 → 4 s | 94.47 → 9.74 s |

除 eager Aligner 外，日志中的独立 JIT kernel warmup 都是 0.00 秒；冷轮主要 JIT 成本反映在
`torch.compile`。热轮成功应用 persisted startup plan 的实例包括 MOSS-Audio、MOSS-TD、
Qwen3-ASR、Whisper 和 Aligner recipe。Aligner review 以及 VibeVoice A / B 因启动时 free-memory
低于所记录 baseline 而回退完整 memory profiling；VibeVoice 还因上游 forward 无法 pickle 而未能
保存 AOT function，所以热轮 compile 仍约 8.2–8.4 秒。MOSS-Audio 热轮报告数个 `/tmp` cubin
无法直接 reload，随后回退并在 0.68 秒完成 compile，最终正常 ready。

### Per-Fixture Execution

| Fixture | 冷 client wall | 冷 trace | 热 client wall | 热 trace | 热 - 冷 trace | 两轮最终状态 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `conversation-weather` | 185.352 s | 183.102 s | 184.703 s | 183.629 s | +0.527 s / +0.29% | 10/10 recipes completed |
| `conversation-education` | 198.607 s | 197.349 s | 197.829 s | 196.618 s | -0.731 s / -0.37% | 10/10 recipes completed |
| `conversation-film` | 221.325 s | 219.910 s | 221.070 s | 219.608 s | -0.302 s / -0.14% | 10/10 recipes completed |
| `meeting-annual-event` | 159.882 s | 159.033 s | 156.979 s | 156.121 s | -2.912 s / -1.83% | 10/10 recipes completed |
| `meeting-game-launch` | 182.500 s | 181.492 s | 191.793 s | 190.747 s | +9.255 s / +5.10% | 10/10 recipes completed |
| `meeting-bike-sharing` | 118.797 s | 118.101 s | 113.180 s | 112.485 s | -5.616 s / -4.76% | 10/10 recipes completed |
| `narration-madmans-diary` | 110.614 s | 109.994 s | 110.456 s | 109.837 s | -0.157 s / -0.14% | 10/10 recipes completed |
| `narration-hometown` | 128.532 s | 127.848 s | 133.881 s | 133.208 s | +5.360 s / +4.19% | 10/10 recipes completed |
| `narration-village-opera` | 140.829 s | 139.962 s | 140.793 s | 139.920 s | -0.042 s / -0.03% | 10/10 recipes completed |
| **合计** | **1446.438 s** | **1436.791 s** | **1450.684 s** | **1442.173 s** | **+5.382 s / +0.37%** | **90/90 recipes completed** |

冷轮首项完成后，仓库外汇总器因把可选 `gpu_sampling_error` 当作必填字段而中止汇总，但 client 和
全部服务产物完整；其 wall time 由 runner `results/` 创建到 client log 落盘的 filesystem birth time
恢复为 185.352 秒。同一方法在热轮得到 184.703 秒，与采集器直接记录完全一致。所有 18 份 trace
均为 `completed`，GPU sampling error 均为空。`meeting-game-launch` 的 VibeVoice joint 在冷 / 热轮
分别保留 2 / 1 个 `RepetitiveGenerationError` 内部事件，随后安全缩窗恢复，五份最终方案仍全部
completed；其余 16 份 trace 没有失败事件。

九项 trace 总耗时热轮比冷轮多 0.37%，逐项变化为 -4.76% 到 +5.10%，没有推理吞吐改善证据。
本轮可确认的收益是完整启动从 698.572 秒降到 88.604 秒，而不是请求执行变快。验证同时通过
`task check:full`（476 项主测试、54 项 ASR 测试及 lint / format / lock / typecheck）、
`prepare.py --check`、current-tree image build、两轮 15/15 ready、两轮九项真实音频和两次正常退出。

### Parallel 2 Throughput Experiment

在上述热轮后，以同一 image、model-data、runtime cache 和 8 卡 placement 重新创建容器，并用
一个 client 对完整 regression root 执行 `--parallel 2`。这是一轮独立的 batch throughput 实验，
不替换前述 `--parallel 1` latency baseline。服务在 87.822 秒达到 15/15 ready，模型 download
log 仍全部为空；九项 batch wall time 为 **1085.083 秒（18.085 分钟）**，相对串行热轮的
1450.684 秒缩短 **365.601 秒 / 25.20%**。同一批 216.750 分钟音频的 wall-clock RTF 从
0.1115 降到 0.0834，处理速度从约 8.97× real-time 提升到 11.99×，等价 batch throughput
提高 33.69%。

| Fixture | 串行热 trace | parallel 2 trace | 单项变化 | 串行 / parallel 2 model queue |
| --- | ---: | ---: | ---: | ---: |
| `conversation-weather` | 183.629 s | 253.177 s | +69.548 s / +37.87% | 9.935 / 66.015 s |
| `conversation-education` | 196.618 s | 353.109 s | +156.491 s / +79.59% | 6.292 / 146.164 s |
| `conversation-film` | 219.608 s | 274.986 s | +55.378 s / +25.22% | 15.237 / 35.647 s |
| `meeting-annual-event` | 156.121 s | 277.398 s | +121.277 s / +77.68% | 5.075 / 106.155 s |
| `meeting-game-launch` | 190.747 s | 226.796 s | +36.049 s / +18.90% | 4.747 / 27.429 s |
| `meeting-bike-sharing` | 112.485 s | 170.058 s | +57.573 s / +51.18% | 2.903 / 40.912 s |
| `narration-madmans-diary` | 109.837 s | 130.105 s | +20.268 s / +18.45% | 6.481 / 11.564 s |
| `narration-hometown` | 133.208 s | 188.549 s | +55.341 s / +41.54% | 5.294 / 45.296 s |
| `narration-village-opera` | 139.920 s | 193.525 s | +53.605 s / +38.31% | 7.440 / 49.134 s |
| **九项 trace 合计** | **1442.173 s** | **2067.703 s** | **+625.530 s / +43.37%** | **63.404 / 528.316 s** |

batch 变短不代表请求变快：九项单独 latency 全部上升，trace 中位数从 156.121 秒增至
226.796 秒，最大值从 219.608 秒增至 353.109 秒。累计 model queue 增至串行的 8.33 倍，
主要来自单实例 FireRed LLM 的 363.356 秒和 Qwen Aligner 的 104.090 秒；CPU queue 仍为 0。
九项 phase 累计中 first pass 从 345.383 秒增至 651.101 秒，review 从 599.855 秒增至
840.115 秒。trace GPU sample 的 GPU 0 / 1 平均 compute busy 从串行的 58.9% / 64.9% 增至
88.6% / 91.2%，说明吞吐收益来自用共享模型排队和单项延迟换取更高设备占用，不是减少了推理量。

本轮九份 trace、45/45 个 recipe 全部 completed，failure 和 GPU sampling error 均为 0；容器
无 OOM、restart 或模型退出。去掉 evidence 引用后，45 份 recipe JSON 中 38 份与串行热轮完全
一致，7 份变化全部来自 VibeVoice；冷 / 热串行轮的 9 份 VibeVoice 也全部彼此不同，因此这不是
足以归因于并发的质量证据，但也不能替代独立指标评估。

因此正式 latency regression 和 committed baseline 刷新继续使用 `--parallel 1`，保证逐项耗时
可比较并维持当前 phase isolation / placement 合同。`--parallel 2` 只适合显式标注的批量吞吐
运行；在把它作为默认工作流前，至少还需独立质量评估，并解决 FireRed LLM 单实例排队以及跨请求
使 GPU 0 / 1 上原本错开的 FireRed、Aligner、Pyannote、Nemotron 阶段发生竞争的问题。仅提高
`cpu_requests`、复用启动 cache 或继续增加 client parallelism 都不会消除这些瓶颈。

### FireRed Two-In-Flight Isolated Experiment

2026-10-12 进一步构建临时 image
`02b3ff58b62c492297794bad6935349c03dc94751eb8006b1046a7000530cd9e`，把 FireRed LLM 的
scheduler 单实例容量和 vLLM `max-num-seqs` 同时从 1 改为 2，其他模型、placement、pipeline 与
client `--parallel 2` 均保持不变。真实 vLLM metrics 在负载中观测到 `num_requests_running=2`、
`num_requests_waiting=0`，因此实验确实触发了 continuous batching，不是配置未生效。

完整九项仍为 45/45 recipes completed，但 batch wall 为 **1095.079 秒**，比原 parallel 2 的
1085.083 秒增加 **9.996 秒 / 0.92%**；九项 trace 合计 2067.703 → 2064.221 秒（-0.17%），
中位数 226.796 → 255.399 秒，均没有端到端收益。FireRed model queue 从 363.356 秒归零，
但其 inference 累计从 1020.455 墍至 1101.773 秒；first pass 因此从 651.101 降至
430.304 秒。提前到达下游的两个请求随后发生新的资源竞争：MOSS-Audio queue 从 19.287 增至
150.145 秒，VibeVoice queue 从 0 增至 200.961 秒。GPU 0 / 1 平均 compute busy 从
88.6% / 91.2% 降至 68.5% / 74.7%，GPU 5 / 6 则从 31.3% / 31.1% 增至 46.7% / 36.1%，
证明瓶颈被搬到下游而非消除。

`meeting-game-launch` 的 VibeVoice 保留两个 `RepetitiveGenerationError` 和一个
`GenerationLimitError` 内部失败事件，exact-core 回退后 04 仍 completed；其 407.567 秒 trace
也是本轮最大离群值。去除 evidence 引用后，33/45 份 recipe JSON 与原 parallel 2 完全一致；
变化包括全部 9 份 VibeVoice，以及 `narration-village-opera` 的 01 / 02 / 05。使用同一 evaluator
复算后，全部 CER、SA-CER 与 DER 均未变化，但这不改变无性能收益的结论。容器无 OOM、restart
或模型退出。

单独放宽 FireRed 不足以保留；该轮之后临时代码曾全部回退。后续组合实验把它与 Aligner placement
一起验证并越过预设门槛，因此最终只把两项变更作为一个优化单元保留。原始单项产物保留在仓库外的
`/workspace/asr-regression-timing/firered2`。

### Rejected Fixed 60s Stagger Experiment

2026-10-12 又以基线 image `ce5d1f2050e3c19e1e7ea0c112b0f1ac25a81f0ae7af1e2370dc1a196c6dd830`
运行一轮完整实验：仍允许最多两个请求在途，但任意两次请求启动至少相隔 60 秒。该外部 runner
不改 server pipeline、模型容量或 placement。容器 0.444 秒进入 running，82.769 秒达到 15/15
ready，13 个 revision marker 启动前已齐全且 download log 全为空。

九项 batch wall 为 **1086.330 秒**，比原 parallel 2 的 1085.083 秒增加
**1.247 秒 / 0.11%**，相对串行热轮仍只缩短 364.354 秒 / 25.12%，没有达到预设的
`<=975` 秒保留门槛。虽然九项 trace 合计从 2067.703 降至 1990.352 秒（-3.74%），中位数从
226.796 降至 206.369 秒（-9.01%），最大值从 353.109 降至 324.248 秒（-8.17%），这些
单项改善没有缩短 batch critical path：

| Fixture | parallel 2 trace | stagger 60 trace | 单项变化 | parallel 2 / stagger 60 model queue |
| --- | ---: | ---: | ---: | ---: |
| `conversation-weather` | 253.177 s | 206.369 s | -46.808 s / -18.49% | 66.015 / 17.143 s |
| `conversation-education` | 353.109 s | 294.180 s | -58.929 s / -16.69% | 146.164 / 67.377 s |
| `conversation-film` | 274.986 s | 324.248 s | +49.262 s / +17.91% | 35.647 / 84.042 s |
| `meeting-annual-event` | 277.398 s | 269.684 s | -7.714 s / -2.78% | 106.155 / 105.728 s |
| `meeting-game-launch` | 226.796 s | 230.003 s | +3.207 s / +1.41% | 27.429 / 23.638 s |
| `meeting-bike-sharing` | 170.058 s | 174.285 s | +4.227 s / +2.49% | 40.912 / 47.789 s |
| `narration-madmans-diary` | 130.105 s | 123.981 s | -6.124 s / -4.71% | 11.564 / 12.942 s |
| `narration-hometown` | 188.549 s | 173.460 s | -15.089 s / -8.00% | 45.296 / 21.099 s |
| `narration-village-opera` | 193.525 s | 194.142 s | +0.617 s / +0.32% | 49.134 / 46.735 s |
| **九项 trace 合计** | **2067.703 s** | **1990.352 s** | **-77.351 s / -3.74%** | **528.316 / 426.493 s** |

固定间隔减少了累计 queue，但没有按照实际 phase 边界错峰。第三个请求在 batch 的 208.121 秒
启动；此时第二个请求已经进入 review 约 9.7 秒，第三个请求随即以 first pass 再次争用 FireRed
与 Aligner。结果 FireRed queue 仅从 363.356 降至 299.732 秒，Aligner queue 从 104.090 降至
102.895 秒，而 first pass 累计反从 651.101 增至 700.867 秒；review 从 840.115 降至
723.634 秒。GPU 0 / 1 的 trace sample 平均 compute busy 仍从 88.6% / 91.2% 微升至
90.2% / 92.3%，说明这两张卡已接近当前 pipeline 的共享资源上限，单纯调固定时间间隔只会重新
分配排队位置。

九份 trace 与 45/45 个 recipe 最终全部 completed，CPU queue 和 GPU sampling error 均为 0，
容器无 OOM、restart 或模型退出。`meeting-game-launch` 保留一个 VibeVoice
`RepetitiveGenerationError` 内部失败事件，176 秒窗口失败后拆成两个约 89 秒窗口完成，04 最终
completed。规范化 JSON key order 并去除 evidence 引用后，37/45 份 recipe JSON 与原
parallel 2 完全一致，变化的 8 份均为本来就非确定的 VibeVoice。使用同一 evaluator 复算后，
变化也只出现在这 8 份：最大绝对 CER 变化 0.443 个百分点、SA-CER 变化 5.990 个百分点，DER
全部不变，且指标有升有降，不构成错峰带来的质量改善证据。

因此不把固定 stagger 参数加入正式 client，正式 latency baseline 仍保持 `--parallel 1`。如果
继续优化 batch，admission 必须读取服务暴露的真实 phase / resource 状态，而不是根据音频开始时间
猜测；但 GPU 0 / 1 已长期高占用，phase-aware admission 的可回收空间预计有限。若目标仍是明显低于
18 分钟，应优先重新设计 FireRed / Aligner placement 或减少 first-pass / review 的实际推理量，
并继续用完整 9-case、质量指标与失败事件作为同一保留门槛。原始产物保留在仓库外的
`/workspace/asr-regression-timing/stagger60`。

### Aligner GPU 7 Isolated Experiment

离线 overlap 分析发现，原 parallel 2 中 Aligner 的 357.103 秒活跃区间有 337.810 秒与
GPU 0 / 1 上的 FireRed 重叠；迁到 GPU 7 后预计只与 Whisper 重叠 23.544 秒。因此构建临时
image `5e184f4b0bf2a1c31d72e380f83645b8a89d0bfd91e3cc46d2d5ced694022031`，把 review 与 recipe
两个 Qwen Aligner 实例都从 GPU 1 / 0 移到 GPU 7，其他代码、容量和 `--parallel 2` 不变。
构建后的首次 container rootfs 创建用了 33.595 秒，服务在 187.290 秒 ready；13 个 revision
marker 启动前已存在，没有模型下载。

九项 batch wall 为 **1033.386 秒**，比原 parallel 2 的 1085.083 秒缩短
**51.697 秒 / 4.76%**，但仍未达到预设的 `<=975` 秒保留门槛。Aligner inference 从
357.839 降到 165.545 秒，queue 从 104.090 降到 27.628 秒；review 累计从 840.115 降到
750.471 秒。FireRed 容量未变，queue 仍为 366.773 秒，说明主 critical path 仍在 FireRed。

九份 trace、45/45 个 recipe 全部 completed，failure、CPU queue 与 GPU sampling error 均为
0。同一 evaluator 与原 parallel 2 对比的变化只来自 VibeVoice；最大绝对 CER / SA-CER 波动为
0.585 / 4.883 个百分点，DER 全部不变。该单项实验没有独立达到保留门槛，但证明 Aligner 迁移
有效并为下述组合消除了原 GPU 0 / 1 上的冲突。原始产物保留在仓库外的
`/workspace/asr-regression-timing/aligner7`。

### Accepted FireRed 2 + Aligner GPU 7 Experiment

最终组合同时启用 FireRed scheduler `max_inflight=2`、vLLM `--max-num-seqs 2`，并把两个
Aligner 实例放到 GPU 7。实验使用已验证的 FireRed2 image
`02b3ff58b62c492297794bad6935349c03dc94751eb8006b1046a7000530cd9e`，bind mount 当前
`server.yaml` 验证组合；13 个 revision marker 启动前已齐全，download log 全为空。container
在 0.450 秒 running，15/15 实例和公开 health 在 **82.975 秒** ready。

完整九项 batch wall 为 **954.364 秒（15.906 分钟）**，通过实验前固定的 `<=975 秒`保留门槛：
相对原 parallel 2 的 1085.083 秒缩短 **130.719 秒 / 12.05%**，相对串行热轮 1450.684 秒
缩短 **496.320 秒 / 34.21%**。同一批 216.750 分钟音频的 wall-clock RTF 为 0.0734，约
13.63× real-time。

| Fixture | parallel 2 trace | 组合 trace | 单项变化 | 组合 model queue |
| --- | ---: | ---: | ---: | ---: |
| `conversation-weather` | 253.177 s | 218.917 s | -34.260 s / -13.53% | 8.523 s |
| `conversation-education` | 353.109 s | 273.422 s | -79.687 s / -22.57% | 64.456 s |
| `conversation-film` | 274.986 s | 297.983 s | +22.997 s / +8.36% | 105.152 s |
| `meeting-annual-event` | 277.398 s | 253.745 s | -23.653 s / -8.53% | 130.672 s |
| `meeting-game-launch` | 226.796 s | 221.461 s | -5.335 s / -2.35% | 22.199 s |
| `meeting-bike-sharing` | 170.058 s | 139.695 s | -30.363 s / -17.85% | 2.088 s |
| `narration-madmans-diary` | 130.105 s | 121.586 s | -8.519 s / -6.55% | 3.841 s |
| `narration-hometown` | 188.549 s | 167.035 s | -21.514 s / -11.41% | 6.633 s |
| `narration-village-opera` | 193.525 s | 161.838 s | -31.687 s / -16.37% | 5.939 s |
| **九项 trace 合计** | **2067.703 s** | **1855.682 s** | **-212.021 s / -10.25%** | **349.503 s** |

组合消除了 FireRed queue（363.356 → 0 秒），代价是 continuous batching 使 FireRed inference
从 1020.455 增至 1105.683 秒。Aligner queue / inference 同时从 104.090 / 357.839 降至
26.323 / 188.030 秒；first pass 从 651.101 降至 447.645 秒，review 从 840.115 降至
768.221 秒。提前释放的请求把部分等待转移到 VibeVoice、MOSS-Audio 和 MOSS-TD，queue 分别为
143.873、109.194 和 27.026 秒，04 累计也从 359.641 增至 444.893 秒。GPU 0 / 1 平均
compute busy 从 88.6% / 91.2% 降到 75.3% / 79.9%，GPU 2 与 GPU 7 升到 52.5% 与 22.7%；
这说明后续空间主要在下游 admission / placement，而非继续增加 FireRed 并发。

九份 trace 和 45/45 个 recipe 最终全部 completed，CPU queue 与 GPU sampling error 均为 0，
容器无 OOM、restart 或模型退出。`meeting-game-launch` 保留一个 VibeVoice
`RepetitiveGenerationError`：176 秒 joint 窗口失败后安全拆窗恢复，04 最终 completed。使用同一
evaluator 与原 parallel 2 比较，10/45 项指标有变化：9 项来自非确定性的 VibeVoice，另 1 项是
`narration-village-opera` 的 FireRed recipe，CER 仅变化 0.019 个百分点。最大绝对 CER 变化
0.480 个百分点；最大 SA-CER 变化是改善 6.521 个百分点，最大退化 5.069 个百分点；DER 全部
不变。所有五套 recipe、失败审计和质量合同均保留，因此正式实现接受这两个耦合变更；正式 latency
baseline 仍维持 `--parallel 1`，组合数字只作为明确标注的 `--parallel 2` throughput 结果。
完整原始产物保留在仓库外的 `/workspace/asr-regression-timing/combined`。

接受变更后，`task check:full` 通过 476 项主测试、55 项 ASR 测试及 lint / format / lock /
typecheck，并从最终工作树构建 image
`0ff410f898f87101789c9d072a3863acaed2fbcc2a916703e24f13a3152c84c1`（12.37 GB）。该 image
首次创建 container rootfs 用时 34.587 秒，15/15 实例和公开 health 在 186.206 秒 ready；所有
revision marker 启动前已存在，download log 全为空。随后用真实 60 秒音频执行 smoke，五套 recipe
全部 completed，14 个 client 产物齐全，trace 12.685 秒、79 个事件、0 failure、GPU sampling error
为空，13 个模型与逻辑 GPU 0–7 均被实际调用。容器正常停止后八卡显存全部回到 0 MiB；最终验证
产物保留在仓库外的 `/workspace/asr-regression-timing/final` 与 `final-smoke`。

### Rejected MOSS-Audio Two-In-Flight Experiment

接受上述组合后，又从最终 image 构建临时派生 image
`ad5a5cfcbd7952fb1eced37130c83a7f06d9133152b2c41fb1bdad76b271e91e`，只把 MOSS-Audio 的
scheduler capacity 与 vLLM `max-num-seqs` 从 1 改为 2。GPU 2 placement、FireRed 双在途、
Aligner GPU 7、pipeline 和 client `--parallel 2` 均不变；实验前预设的增量保留门槛为
`<=935` 秒，即至少比 954.364 秒再快约 2%。

完整九项 batch wall 为 **965.346 秒**，比已接受组合增加 **10.982 秒 / 1.15%**，未达到保留
门槛。九项 trace 合计虽然从 1855.682 降到 1825.394 秒（-30.288 秒 / -1.63%），中位数从
218.917 降到 211.051 秒，但改善没有落在 batch critical path：

| Fixture | 接受组合 trace | MOSS-Audio 2 trace | 单项变化 |
| --- | ---: | ---: | ---: |
| `conversation-weather` | 218.917 s | 225.753 s | +6.836 s / +3.12% |
| `conversation-education` | 273.422 s | 260.920 s | -12.502 s / -4.57% |
| `conversation-film` | 297.983 s | 290.021 s | -7.962 s / -2.67% |
| `meeting-annual-event` | 253.745 s | 211.051 s | -42.694 s / -16.82% |
| `meeting-game-launch` | 221.461 s | 232.352 s | +10.891 s / +4.92% |
| `meeting-bike-sharing` | 139.695 s | 163.509 s | +23.814 s / +17.05% |
| `narration-madmans-diary` | 121.586 s | 135.023 s | +13.437 s / +11.05% |
| `narration-hometown` | 167.035 s | 160.270 s | -6.765 s / -4.05% |
| `narration-village-opera` | 161.838 s | 146.495 s | -15.343 s / -9.48% |

MOSS-Audio queue 从 109.194 秒归零，inference 只从 533.825 增至 541.972 秒，review 也从
768.221 降到 711.097 秒；但更早进入下游的两个请求使 VibeVoice queue 从 143.873 增至
213.150 秒、MOSS-TD 从 27.026 增至 61.122 秒、Aligner 从 26.323 增至 41.529 秒，04 累计
从 444.893 增至 487.705 秒。与 FireRed 单项实验相同，这次只是把等待从一个独占模型搬到下游
共享阶段，不能用累计 queue 或 trace 合计代替 batch wall 裁决。

九份 trace 和 45/45 个 recipe 全部 completed，CPU queue 与 GPU sampling error 均为 0。
`meeting-game-launch` 保留两个 VibeVoice `RepetitiveGenerationError`，安全拆窗后 04 completed。
同一 evaluator 对比接受组合，最大绝对 CER / SA-CER 波动为 0.358 / 3.486 个百分点，DER 全部
不变。质量合同通过但性能门槛失败，因此 MOSS-Audio capacity、`max-num-seqs` 与对应临时测试改动
全部回退，正式实现仍保持 MOSS-Audio 单在途。原始产物保留在仓库外的
`/workspace/asr-regression-timing/moss2`。

### Accepted VibeVoice Two-In-Flight Experiment

随后从最终 image 构建临时派生 image
`1e5cbc76b4430c8f71e04de708ee6e0849c1b53c65f7eb5a500a7cce62f41124`，只把两个 VibeVoice
实例的 scheduler capacity 与 vLLM `max-num-seqs` 从 1 改为 2。其余 accepted 组合配置不变，
继续使用预设的 `<=935` 秒增量保留门槛。

完整九项 batch wall 为 **918.341 秒（15.306 分钟）**，比前一 accepted 组合的 954.364 秒
再缩短 **36.023 秒 / 3.77%**，比最初 parallel 2 的 1085.083 秒缩短
**166.742 秒 / 15.37%**，相对串行热轮 1450.684 秒缩短 **532.343 秒 / 36.70%**。九项
trace 合计从 1855.682 降到 1781.239 秒（-74.443 秒 / -4.01%），中位数从 218.917 降到
214.579 秒，最大值从 297.983 降到 277.736 秒。

| Fixture | 前一组合 trace | VibeVoice 2 trace | 单项变化 |
| --- | ---: | ---: | ---: |
| `conversation-weather` | 218.917 s | 227.131 s | +8.214 s / +3.75% |
| `conversation-education` | 273.422 s | 277.736 s | +4.314 s / +1.58% |
| `conversation-film` | 297.983 s | 249.926 s | -48.057 s / -16.13% |
| `meeting-annual-event` | 253.745 s | 214.579 s | -39.166 s / -15.44% |
| `meeting-game-launch` | 221.461 s | 231.001 s | +9.540 s / +4.31% |
| `meeting-bike-sharing` | 139.695 s | 135.656 s | -4.039 s / -2.89% |
| `narration-madmans-diary` | 121.586 s | 118.484 s | -3.102 s / -2.55% |
| `narration-hometown` | 167.035 s | 159.097 s | -7.938 s / -4.75% |
| `narration-village-opera` | 161.838 s | 167.629 s | +5.791 s / +3.58% |

VibeVoice queue 从 143.873 秒归零，inference 从 702.072 增至 715.008 秒，04 累计从
444.893 降至 369.684 秒。FireRed queue 仍为 0；MOSS-Audio queue 从 109.194 微增至
119.945 秒，其余主要模型 queue 与 phase 耗时保持同量级。九份 trace、45/45 个 recipe 全部
completed，failure、CPU queue 与 GPU sampling error 均为 0；同一 evaluator 的指标变化只来自
VibeVoice，最大绝对 CER 变化为改善 1.471 个百分点，最大绝对 SA-CER 变化为改善 6.138 个百分点，
DER 全部不变。

默认 pool 策略按配置顺序选择仍有容量的实例，因此本轮 93 次 VibeVoice 调用中 GPU 5 的 A 副本
承接 87 次，GPU 6 的 B 副本承接 6 次。为确认这不是错误的局部最优，另用临时 image
`b5f6ce0a0118b4f6ce5404bb80bc3e5e4337259d975d5e103159322854939e5a` 把 scheduler 改为
最少在途优先。该轮 A / B 调用恢复为 48 / 47，但 batch 反增至 **970.367 秒**，未过门槛；
MOSS-Audio queue 从 119.945 增至 165.395 秒，MOSS-TD 从 25.807 增至 71.650 秒，说明主动使用
GPU 6 会把 VibeVoice 与另一请求的 Paraformer first pass 重叠。该轮仍为 45/45 completed，保留
一个安全恢复的 VibeVoice 重复生成事件，最大绝对 CER / SA-CER 波动 1.506 / 3.779 个百分点，
DER 不变。

因此正式实现保留 VibeVoice 每副本两个 slot 和 `max-num-seqs=2`，但维持 scheduler 的配置顺序
first-available 选择：A 用于同卡 continuous batching，B 作为超过两个并发调用时的溢出。两个实验
的原始产物分别保留在仓库外的 `/workspace/asr-regression-timing/vibe2` 与 `vibe2-balanced`。

正式落地后，`task check:full` 再次通过 476 项主测试、55 项 ASR 测试及 lint / format / lock /
typecheck，并从最终工作树构建 12,370,508,558-byte image
`9364f2288be0d94c9a72ba0f058831cffa80c36dc6b9321e17c17309c0e735d7`。首次创建 container
rootfs 与进入 running 用时 35.842 秒；13 个既有 revision marker 在 35.872 秒全部确认，没有
下载模型。15/15 实例及公开 health 在 **181.463 秒** ready，即 running 后的模型加载、JIT 与
health 长尾为 145.621 秒；最慢的 FireRed LLM 与两个 VibeVoice 实例分别在 178.261 与
180.622 秒 ready。

随后用真实 60 秒音频执行 smoke，五套 recipe 全部 completed，14 个 client 产物齐全；trace
12.864 秒，79 / 79 个事件 completed，evidence error、failure 与 GPU sampling error 均为 0。
13 个逻辑模型与 GPU 0–7 均有实际调用；请求后八卡驻留显存依次为 26,425 / 30,494 / 31,873 /
43,505 / 9,935 / 42,936 / 41,082 / 31,588 MiB。容器无 OOM、restart 或模型退出，正常停止并
自动删除后八卡显存全部回到 0 MiB，也无残留 compute process。最终启动、运行日志和 smoke
产物保留在仓库外的 `/workspace/asr-regression-timing/final-vibe2`。

### Accepted MOSS-Audio Two-In-Flight And Phase-Aware Review Placement

2026-10-12 在上述 VibeVoice 双在途实现上继续组合三项改动：MOSS-Audio scheduler capacity 与
vLLM `max-num-seqs` 同时改为 2；多人窗口不再执行不会被 fusion 或 joint recipes 消费的 review；
review Aligner 从 GPU 7 移到 GPU 6，recipe Aligner 保持 GPU 7。后一项是按 pipeline phase
设计的静态 placement，不是运行期迁移或追求八卡平均占用：GPU 6 上的 Paraformer 属于 first
pass，review Aligner 属于 review，VibeVoice B 只承接超过 A 两个 slot 的 04 overflow。

完整九项 `--parallel 2` batch wall 为 **825.343 秒（13.756 分钟）**，通过实验前固定的
`<=845 秒`保留门槛。相对前一 accepted VibeVoice 2 结果 918.341 秒缩短
**92.998 秒 / 10.13%**；相对最初 parallel 2 的 1085.083 秒缩短
**259.740 秒 / 23.94%**，相对串行热轮 1450.684 秒缩短 **625.341 秒 / 43.11%**。
九项 trace 合计从 1781.239 降到 1559.879 秒（-221.360 秒 / -12.43%）。

| Fixture | VibeVoice 2 trace | 当前组合 trace | 单项变化 |
| --- | ---: | ---: | ---: |
| `conversation-weather` | 227.131 s | 232.371 s | +5.240 s / +2.31% |
| `conversation-education` | 277.736 s | 236.085 s | -41.651 s / -15.00% |
| `conversation-film` | 249.926 s | 230.044 s | -19.882 s / -7.96% |
| `meeting-annual-event` | 214.579 s | 167.640 s | -46.939 s / -21.87% |
| `meeting-game-launch` | 231.001 s | 135.917 s | -95.084 s / -41.16% |
| `meeting-bike-sharing` | 135.656 s | 112.635 s | -23.021 s / -16.97% |
| `narration-madmans-diary` | 118.484 s | 128.822 s | +10.338 s / +8.73% |
| `narration-hometown` | 159.097 s | 163.858 s | +4.761 s / +2.99% |
| `narration-village-opera` | 167.629 s | 152.507 s | -15.122 s / -9.02% |

多人窗口仍整窗禁止替换，且 03 / 04 joint recipes 从不读取 review 文本，所以跳过这些调用不改变
任何 recipe 的输入合同。九项共识别出 183 个多人窗口，其中 182 个在前一实现会进入 review；
MOSS-Audio 调用从 785 降到 603，全部 Aligner 调用从 5137 降到 4454，review phase 累计从
771.947 降到 518.676 秒。MOSS-Audio 双在途同时把其 model queue 从 119.945 秒降到 0；
由于调用量也减少，不能把全部 batch 收益单独归因于 capacity，三项改动只作为完整组合接受。

GPU 6 的 trace sample 平均 compute busy 从 4.9% 升到 9.2%，GPU 7 从 24.1% 降到 17.6%；
新的八卡平均值依次为 75.5%、82.0%、34.4%、27.2%、29.1%、42.7%、9.2%、17.6%。GPU 6
仍低于其他卡不是 scheduler 缺陷：VibeVoice B 是保护下游 phase 的 overflow，强制 least-inflight
均分 A / B 的独立实验已使 batch 从 918.341 增到 970.367 秒。当前 placement 用 GPU 6 的空闲
窗口承接短 Paraformer / review Aligner 调用，同时避免主动制造长 VibeVoice 与另一请求 first pass
的重叠；真正接近瓶颈的是 GPU 0 / 1，而不是 GPU 6 的平均值。

九份 trace 和 45/45 recipes 全部 completed，CPU queue 与 GPU sampling error 均为 0。
`meeting-bike-sharing` 有两个 VibeVoice `RepetitiveGenerationError`，均拆窗恢复，最终 evidence
error 为 0。相对 VibeVoice 2 的 45 项质量结果，只有 9 项非确定性 VibeVoice 输出变化；最大绝对
CER / SA-CER 波动为 1.559 / 7.283 个百分点，DER 全部不变，其余四套 recipe 指标完全一致。
当前代码通过 `task check:full`：476 项主测试、56 项 ASR 测试及 lint / format / lock /
typecheck。完整性能与质量产物保留在仓库外的 `/workspace/asr-regression-timing/review-phase`。

正式 Dockerfile 构建连续两次在获取固定 FireRedASR2S GitHub revision 时因 Host 无法连接
`github.com:443` 失败，代码、锁文件和测试阶段没有失败。为完成运行验证，从前一正式 image 叠加
本轮 runtime 文件构建了无 bind mount 候选 image
`0ad967fcc80d86650e69c681a589acaef920c312242476784a74921c2dca36f2`（12,370,467,368 bytes）。
首次创建该 image 的 container rootfs 用时 34.044 秒，15/15 实例与公开 health 在 111.546 秒
ready，即容器内启动 77.502 秒；复用旧 rootfs 的正式旧 image 二次热启为 80.769 秒，组合实验
候选为 78.730 秒。MOSS-Audio ready 从 58.953 提前到 53.045 秒，其 CUDA Graph capture 从
7 秒降到 1 秒。不能把首次 rootfs 创建抖动当作模型初始化回归；网络恢复后仍需用正式 Dockerfile
重建同一工作树 image。

最后对无代码挂载候选运行真实 60 秒音频 smoke：五套 recipe 全部 completed，14 个产物齐全，
trace 为 12.684 秒、79/79 events completed、0 error，模型事件覆盖逻辑 GPU 0–7。容器正常停止
并自动删除后八卡显存和 compute utilization 全部为 0；startup、日志与 smoke 产物保留在仓库外的
`/workspace/asr-regression-timing/optimized-final`。

### Accepted Qwen3-ASR Two-In-Flight Experiment

在上一组合上只把 Qwen3-ASR scheduler capacity 与 vLLM `max-num-seqs` 从 1 改为 2，预先固定
增量保留门槛为 `<=808.836 秒`，即至少比 825.343 秒再快 2%。完整九项 batch wall 为
**804.279 秒（13.405 分钟）**，缩短 **21.064 秒 / 2.55%**，通过门槛；九项 trace 合计从
1559.879 降到 1514.018 秒（-45.861 秒 / -2.94%）。

真实 vLLM metrics 日志观测到 `Running: 2 reqs, Waiting: 0 reqs`，确认 continuous batching
实际发生。Qwen3-ASR queue 从 52.618 秒降到 0，总 model queue 从 246.290 降到 72.712 秒；
review phase 从 518.676 降到 496.532 秒。GPU 4 平均 compute busy 为 28.2%，说明收益来自消除
短窗口间的 scheduler 排队，而不是提高长期平均占用。九份 trace 和 45/45 recipes 全部
completed，CPU queue 与 GPU sampling error 均为 0；两个 VibeVoice 重复生成事件均拆窗恢复。

相对上一组合，最大绝对 CER / SA-CER 波动为 1.243 / 7.656 个百分点，仍由非确定性 VibeVoice
主导；排除 04 后最大值仅为 0.146 / 0.160 个百分点，DER 全部不变。候选首次创建 rootfs 后
119.632 秒 ready，其中 Qwen3-ASR 首次为新 sequence shape 捕获 graph 并成为 119.629 秒启动
长尾；该成本不进入 batch wall。复用新 graph cache 的最终热启动为 **76.844 秒**，比改动前
80.769 秒缩短 3.925 秒 / 4.86%，Qwen3-ASR 在 52.971 秒 ready。

最终无代码挂载候选 image 为
`00b4d39aeba8517756a0d68c41d61931df623091c357d6ebeb1ca122a4fba58c`（12,370,483,409 bytes）。
真实 60 秒音频 smoke 的 trace 为 12.712 秒，79/79 events completed、0 failure，五套 recipe、
14 个产物和逻辑 GPU 0–7 覆盖均通过；容器正常停止后八卡显存和 compute utilization 全为 0。
完整产物保留在仓库外的 `/workspace/asr-regression-timing/qwen2` 与 `qwen-final`。

### Rejected Whisper Two-In-Flight Experiment

随后只把 Whisper scheduler capacity 与 vLLM `max-num-seqs` 改为 2。vLLM 对 encoder-decoder
模型要求单个 30 秒音频约 1500 encoder tokens；其默认 896-token batch budget 无法启动，因此
候选显式设置 `max-num-batched-tokens=3000` 后才完成验证。修正后首次创建 rootfs 的服务在
113.859 秒 ready，真实日志同样观测到两个请求同时 running。

完整九项 batch wall 为 **816.284 秒**，比 Qwen3-ASR 2 基线增加 **12.005 秒 / 1.49%**，没有
达到 `<=788.193 秒`的增量门槛；九项 trace 合计也从 1514.018 增到 1519.167 秒。Whisper queue
虽然从 5.784 秒降到 0，但总 model queue 反从 72.712 增到 91.086 秒，其中 MOSS-TD 从
14.970 增到 29.280 秒、Aligner 从 30.081 增到 35.046 秒。收益不在 critical path，并把执行
时序扰动传给下游，因此正式实现回退 Whisper 的两个参数，保持单在途。

该轮仍为 45/45 recipes completed、CPU queue 与 GPU sampling error 为 0；一个 VibeVoice
重复生成事件安全恢复，DER 全部不变。最大绝对 CER / SA-CER 波动为 0.939 / 6.504 个百分点，
主要来自非确定性 VibeVoice。原始启动、性能与质量产物保留在仓库外的
`/workspace/asr-regression-timing/whisper2`。

### Accepted VibeVoice AOT Cache Repair

2026-10-12 修复 VibeVoice 每次启动重复 `torch.compile` 的问题。Transformers 装饰后的
`Qwen2Model.forward` 两层 inner function 与外层共享同一个 module / qualname，Torch AOT
因此无法 pickle；给 inner function 注册稳定 module-level identity 后可以保存 artifact。首次
候选又暴露 Dynamo 为不在 function globals 中的 `collections` module 生成含进程内 object ID
的临时引用，下一进程无法恢复。最终 launcher 在模块导入期同时注册稳定 function identity，并
把 `collections` 注入三层 wrapper globals；模块顶层执行保证 vLLM multiprocessing spawn 的
engine 子进程也应用修复，没有修改 site-packages 或关闭 AOT。

最终无代码挂载候选 image 为
`f61191dde646734271a6901116103484e9912dab7f48c2ebaaa5d6068d8075b5`（12,370,494,312 bytes）。
移走旧的无效 artifact 后，第一轮创建 container rootfs 用时 35.837 秒，VibeVoice A / B 在
119.024 秒 ready，公开 health 在 119.316 秒 ready；两个 engine 均记录
`saved AOT compiled function`，compile 分别为 8.97 / 9.17 秒，engine init 为
26.79 / 27.25 秒，且无 pickle 或 missing-globals 错误。

正常停止并确认八卡显存清零后，第二轮 container running 用时 0.522 秒。两个 engine 均记录
`Directly load AOT compilation`，compile 降至 0.29 / 0.60 秒，分别减少 8.68 / 8.57 秒；
engine init 降至 19.41 / 19.65 秒，分别减少 7.38 / 7.60 秒。VibeVoice A / B 在 93.867 秒
ready；本轮公开 health 为 106.225 秒，长尾已变为 FireRed LLM（105.327 秒）而不是
VibeVoice。该次整服务 wall time 高于此前 76.844 秒热启动，反映所有模型并行启动时的 Host
抖动，不能把局部 AOT 收益等同为整服务必然缩短；可重复结论是 VibeVoice 自身 compile 与
engine-init 阶段减少约 8.6 秒和 7.5 秒。

第二轮 ready 后用真实 60 秒 WAV 完成 smoke：五套 recipe 全部 completed，14 个 client 产物
齐全；trace 为 19.697 秒、79 / 79 events completed、0 model failure，VibeVoice joint inference
为 1.967 秒。容器正常停止后八卡显存全部为 0 MiB。最终两轮 startup、模型日志和 smoke 产物
保留在仓库外的 `/workspace/asr-regression-timing/vibe-aot-cold`、`vibe-aot-hot` 与
`vibe-aot-smoke`；两个中间失败阶段分别保留为 `vibe-aot-cold-failed-v1` 和
`vibe-aot-{cold,hot}-missing-globals`，不计为最终结果。

最终工作树通过 `task check:full`：476 项主测试、56 项 ASR 测试及 lint / format / lock /
typecheck 全部通过；正式 Dockerfile 构建成功，image 为
`db64935a2f739d2d057b3ad89cdb82e5fdc01e96dd6d4e508d3a011760b7bf29`
（12,370,511,626 bytes）。

### Startup Optimization Closure

2026-10-13 以该正式 image 重新建立可比启动基线。新 image 首次创建 container rootfs 用时
34.563 秒，首次生成本轮 JIT / AOT cache 后公开 health 在 **178.333 秒** ready；不删除任何
持久 cache 的第二轮 container running 为 0.425 秒，15/15 实例及公开 health 在
**74.683 秒** ready。热轮长尾为 FireRed LLM 74.402 秒，其后是 MOSS-TD 68.494 秒和
VibeVoice A / B 66.113 秒。FireRed 内部约有 16 秒 API / processor 前置初始化、9 秒 TP worker
spawn 与 NCCL 初始化、6.1 秒模型加载、0.36 秒 AOT 加载、11.13 秒 engine init，以及约 5 秒
processor / API 后置初始化；继续只优化权重或 AOT 已不足以明显改变整服务 critical path。

以热基线至少改善 2%（`<=73.189 秒`）作为增量保留门槛，随后逐项验证了五个候选：

| 候选 | 冷轮 service / rootfs | 热轮 service | 相对 74.683 秒 | 结论 |
| --- | ---: | ---: | ---: | --- |
| 七个重模型优先、其余延后 10 秒 | 107.441 / 33.994 s | 75.705 s | +1.022 s / +1.37% | 重模型仍彼此争用，回退 |
| FireRed `--skip-mm-profiling` | 104.006 / 33.496 s | 73.662 s | -1.021 s / -1.37% | 未过门槛，且转移 encoder 峰值显存责任，回退 |
| FireRed 单实例提前 5 秒 | 107.084 / 33.818 s | 74.709 s | +0.026 s / +0.03% | MOSS-TD 被推到新长尾，回退 |
| `VLLM_ENABLE_V1_MULTIPROCESSING=0` | 108.216 / 33.682 s | 73.632 s | -1.051 s / -1.41% | API serving 仍创建独立 EngineCore PID，差异是抖动，回退 |
| TP worker 使用 `fork` | 未 ready / 34.439 s | 未执行 | 不适用 | NCCL 建链成功后权重加载固定停在 1/9 shard，回退 |

`fork` 候选实际创建两个 TP worker 并完成 NCCL rank 初始化，不是参数未生效；但多线程 loader
在 fork 后继承了不安全状态，FireRed 永远没有 ready。保存失败日志后正常停止容器，未尝试用
关闭多线程 loader 掩盖该可靠性问题。inline EngineCore 候选的热轮虽有约 1 秒表面改善，但日志中
APIServer 与 EngineCore 仍是不同 PID，冷轮扣除 rootfs 后反而比基线慢 0.276 秒，因此不能归因
为实现收益。所有候选均未进入正式代码，最终 scheduler 继续一次 s6 transaction 并行启动全部
实例，FireRed 保留完整 multimodal profiling 和安全的 spawn worker。

本轮结论是当前依赖版本和 15 个常驻实例合同下，没有已验证、低风险且达到 2% 的剩余启动参数
优化。继续显著降低 74.683 秒热启动需要改变更大的边界，例如上游支持安全的预初始化 worker /
processor snapshot、升级到具备更低 multiprocessing 开销且通过完整质量回归的 serving 版本，或
减少同步 ready 前必须常驻的模型；不能通过 lazy ready 把耗时转移到首请求。上述启动证据分别保留
在仓库外的 `/workspace/asr-regression-timing/` 对应 `startup-*-cold` 与 `startup-*-hot`
目录，fork 失败证据保留在 `startup-fork-cold`。每次停止后 GPU 0–7 显存均回到 0 MiB。

## Layout And Workflow

| 路径 | Ownership |
| --- | --- |
| `manifest.yaml` | 固定 source revision、HTTPS URL、source/output SHA256、音频属性、speaker metadata 和 reference 规则；audio-verbatim 同时固定底本与参考 checksum |
| `<category>/audio/` | 可删除、可重建的本地 cache；被 `.gitignore` 忽略 |
| `<category>/results/<audio-name>/` | 五套 recipe 的 committed raw baseline 和可审计 trace |
| `<category>/*.txt` / `*.TextGrid` | 已提交的标准答案；修改后同步 manifest SHA256 |
| `metrics.json` | `evaluate.py` 从 committed results 确定性生成的指标 |

准备或验证 cache：

```bash
uv run --script platform/container/services/asr/regression/prepare.py
uv run --script platform/container/services/asr/regression/prepare.py --check
```

服务 ready 后串行刷新三类 baseline；只有确实要替换 committed baseline 时才使用
`--overwrite`：

```bash
for category in conversation meeting narration; do
  uv run platform/container/services/asr/client/asr.py \
    "platform/container/services/asr/regression/$category/audio" \
    --server http://127.0.0.1:8080 \
    --out "platform/container/services/asr/regression/$category/results" \
    --parallel 1 \
    --overwrite
done
uv run --script platform/container/services/asr/regression/evaluate.py --markdown
```

MagicData 音频保持官方完整 WAV，不裁切或转码。AliMeeting 由固定原始 8-channel WAV
确定性提取 channel 0 的前 20 分钟 PCM，转换合同在 `prepare.py`。LibriVox 使用原始 MP3；
正文区间排除每篇开头和结尾的 LibriVox announcement。
