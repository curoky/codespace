# ASR Regression

本目录保存 ASR 的固定 9 音频 corpus、标准答案、最新 committed result 和确定性质量指标。本文
只记录当前可复现基线与操作合同；实验过程由 Git history 和仓库外原始日志承担，不在这里累积
逐轮调优记录。

## Corpus

`manifest.yaml` 是 source of truth，固定 source revision、下载 URL、checksum、转换规则、音频
属性、speaker metadata 和 reference 规则。CER 与 SA-CER 使用逐字 transcript reference；meeting
DER 使用 `diar-forced-alignment` 固定 revision 的 AliMeeting Test Far RTTM，conversation DER 使用
MagicData gold timing。DER 为 0 秒 collar 且保留 overlap。指标单元格依次为
**CER / SA-CER / DER**，均为越低越好；`—` 表示单 speaker fixture 不适用该指标。

| Fixture | 来源 / License | 类型 | 内容 | 时长 | 大小 | 01 Qwen fusion | 02 FireRed fusion | 03 MOSS-TD | 04 VibeVoice | 05 Qwen + Nemotron |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `conversation-weather` | [MagicData-RAMC dev](https://huggingface.co/datasets/EaseZh/magicdata_ramc/tree/79d508c3c3de40a0db55135f78113a7dfe6066d2) / CC BY-NC-ND 4.0 | 双人自然对话；gold | 天气、气候与生活体验 | 30:07.875 | 55.17 MiB | 7.89% / 9.49% / 10.60% | 7.80% / 8.84% / 10.60% | 7.51% / 7.51% / 5.97% | 9.45% / 9.45% / 15.15% | 7.92% / 20.58% / 21.83% |
| `conversation-education` | [MagicData-RAMC dev](https://huggingface.co/datasets/EaseZh/magicdata_ramc/tree/79d508c3c3de40a0db55135f78113a7dfe6066d2) / CC BY-NC-ND 4.0 | 双人自然对话；gold | 学校、专业与就业规划 | 32:18.350 | 59.15 MiB | 6.41% / 9.59% / 14.01% | 7.23% / 10.25% / 14.01% | 5.96% / 8.04% / 12.05% | 8.66% / 10.55% / 24.34% | 6.41% / 9.57% / 16.46% |
| `conversation-film` | [MagicData-RAMC dev](https://huggingface.co/datasets/EaseZh/magicdata_ramc/tree/79d508c3c3de40a0db55135f78113a7dfe6066d2) / CC BY-NC-ND 4.0 | 双人自然对话；gold | 《哪吒》剧情、票房与角色 | 30:58.400 | 56.71 MiB | 10.02% / 12.08% / 10.84% | 10.32% / 12.17% / 10.84% | 7.96% / 8.23% / 5.85% | 12.61% / 13.10% / 18.73% | 10.02% / 11.64% / 14.46% |
| `meeting-annual-event` | [AliMeeting test](https://huggingface.co/datasets/ggfox00000/dia-alimeeting-test/tree/cef2837c4a1a0762074522c1bbbbb90eb4d1acf5) / CC BY-SA 4.0 | 四人远场会议；gold | 年会、节目与抽奖安排 | 20:00.000 | 36.62 MiB | 26.57% / 40.27% / 26.88% | 34.51% / 44.82% / 26.88% | 15.67% / 11.70% / 19.05% | 33.67% / 38.49% / 37.89% | 27.01% / 34.21% / 8.96% |
| `meeting-game-launch` | [AliMeeting test](https://huggingface.co/datasets/ggfox00000/dia-alimeeting-test/tree/cef2837c4a1a0762074522c1bbbbb90eb4d1acf5) / CC BY-SA 4.0 | 四人远场会议；gold | 手游用户、奖励与卖点 | 20:00.000 | 36.62 MiB | 55.91% / 69.52% / 39.71% | 65.04% / 72.65% / 39.71% | 39.09% / 32.66% / 31.24% | 61.80% / 78.79% / 77.55% | 56.22% / 70.62% / 20.29% |
| `meeting-bike-sharing` | [AliMeeting test](https://huggingface.co/datasets/ggfox00000/dia-alimeeting-test/tree/cef2837c4a1a0762074522c1bbbbb90eb4d1acf5) / CC BY-SA 4.0 | 三人远场会议；gold | 单车停放、安全与治理 | 20:00.000 | 36.62 MiB | 14.90% / 19.07% / 22.96% | 32.34% / 36.10% / 22.96% | 12.95% / 10.03% / 18.45% | 24.88% / 41.24% / 36.37% | 15.05% / 17.54% / 5.69% |
| `narration-madmans-diary` | [LibriVox《呐喊》](https://archive.org/details/call_to_arms_jl_librivox) / Public Domain | 单人朗读；audio-verbatim | 鲁迅《狂人日记》 | 20:34.245 | 18.84 MiB | 2.49% / — / — | 2.22% / — / — | 2.94% / — / — | 2.10% / — / — | 2.49% / — / — |
| `narration-hometown` | [LibriVox《呐喊》](https://archive.org/details/call_to_arms_jl_librivox) / Public Domain | 单人朗读；source text | 鲁迅《故乡》 | 20:25.213 | 18.70 MiB | 2.15% / — / — | 1.84% / — / — | 2.71% / — / — | 3.04% / — / — | 2.15% / — / — |
| `narration-village-opera` | [LibriVox《呐喊》](https://archive.org/details/call_to_arms_jl_librivox) / Public Domain | 单人朗读；source text | 鲁迅《社戏》 | 22:20.920 | 20.46 MiB | 2.99% / — / — | 3.12% / — / — | 3.72% / — / — | 3.22% / — / — | 2.99% / — / — |

conversation 不裁切或转码。meeting 的确定性音频抽取由 `prepare.py` 实现，RTTM 在评分时裁到
相同的前 20 分钟。narration 评估正文区间排除 LibriVox 开头与结尾 announcement；单 speaker
语料不计算 SA-CER 和 DER。

## Latest Baseline

本节的 9 音频 committed baseline 于 2026-10-13 从正式 image
`e791f212cf519ae5d83f51038fde2747d56a1291e7929f0f04b33829721dc993`
生成，未使用代码 bind mount。image 未压缩大小为 12,370,497,805 bytes。13 个固定 model
revision marker 全部命中，模型下载阶段为 0 秒。

### Build And Automated Tests

- `task check:full` 通过：476 项主测试、68 项 ASR 测试，以及 format、lint、type、lock、Shell
  检查。
- 正式 Dockerfile build 成功；所有模型环境从 lock 安装并完成 hardlink 去重。
- 9 份 trace 全部 `completed`，45/45 recipes 全部 `completed`。
- 12,715 个 trace events completed，最终 recipe、trace 与 evidence 无 error。
- 1,156 组 GPU samples 无采样错误；容器 restart count 为 0、未 OOM、没有模型异常退出。

### Startup

本轮从精确 image ID 启动，15/15 实例 ready 后公开 `/health`。全部回归完成后正常停止容器，
GPU 0–7 均回到 0 MiB。本轮未把启动 wall 作为性能测量，不沿用其他 image 的冷 / 热启动数字。

### End-To-End Performance

正式 committed baseline 使用 `--parallel 1`，避免跨文件竞争污染单项质量与 trace。九条
server trace 合计 1,292.708 秒（21.545 分钟），中位数 127.813 秒，最大 206.102 秒。

| Fixture | 音频时长 | Trace wall | Trace / audio | 最终状态 |
| --- | ---: | ---: | ---: | --- |
| `conversation-weather` | 1,807.875 s | 172.098 s | 0.095× | 5/5 recipes completed |
| `conversation-education` | 1,938.350 s | 182.905 s | 0.094× | 5/5 recipes completed |
| `conversation-film` | 1,858.400 s | 206.102 s | 0.111× | 5/5 recipes completed |
| `meeting-annual-event` | 1,200.000 s | 127.813 s | 0.107× | 5/5 recipes completed |
| `meeting-game-launch` | 1,200.000 s | 126.212 s | 0.105× | 5/5 recipes completed |
| `meeting-bike-sharing` | 1,200.000 s | 93.367 s | 0.078× | 5/5 recipes completed |
| `narration-madmans-diary` | 1,234.245 s | 110.658 s | 0.090× | 5/5 recipes completed |
| `narration-hometown` | 1,225.213 s | 133.331 s | 0.109× | 5/5 recipes completed |
| `narration-village-opera` | 1,340.920 s | 140.222 s | 0.105× | 5/5 recipes completed |
| **合计** | **13,005.003 s** | **1,292.708 s** | **0.099×** | **45/45 recipes completed** |

串行质量回归中的 GPU 平均 compute busy 为 52.8%、59.1%、26.6%、22.9%、17.9%、30.4%、
2.5%、10.8%。这不是 throughput placement 评分：GPU 6 承担短 Paraformer、review Aligner 和
VibeVoice overflow，串行单文件不会主动使用 overflow。placement 的验收目标是 critical path、
phase 隔离和无 queue 回归，不是八卡平均利用率相等。

### Quality

下表来自最新 `metrics.json` 的 9-fixture macro。详细 45 项结果以该文件和
`evaluate.py --markdown` 输出为准。

| Recipe | Completed | Macro CER | Macro SA-CER | Macro DER |
| --- | ---: | ---: | ---: | ---: |
| `01-qwen-fusion` | 9/9 | 14.37% | 26.67% | 20.83% |
| `02-firered-fusion` | 9/9 | 18.27% | 30.81% | 20.83% |
| `03-moss-td` | 9/9 | **10.95%** | **13.03%** | 15.43% |
| `04-vibevoice` | 9/9 | 17.72% | 31.94% | 35.01% |
| `05-qwen-nemotron` | 9/9 | 14.47% | 27.36% | **14.61%** |

conversation 的最低 macro CER / SA-CER / DER 都是 03（7.15% / 7.93% / 7.96%）；meeting 的最低
CER / SA-CER 是 03（22.57% / 18.13%），最低 DER 是 05（11.65%）；narration 最低 CER 是 02
（2.40%）。03 的全局一对一 speaker 映射显著改善 attribution，且正文仍是五方案中最好。

04 现在同样按 joint model 自有 segment 计算 speaker activity，不再复用 Pyannote activity。其
meeting macro SA-CER / DER 为 52.84% / 50.61%，说明旧口径掩盖了 VibeVoice 自身 diarization 的
真实弱点；这不是可接受的 speaker 基线，后续优化不能再通过共享外部 activity 隐藏问题。

meeting DER reference 使用 Nemotron 官方评估采用的 forced-alignment RTTM，而不是面向转写的
原始 TextGrid segment；后者会把段内静音计作语音，不适合 frame-level DER。当前 05 的 meeting
DER 为 11.65%，与模型报告的 AliMeeting Test Far 10.47% 处于同一量级；本 corpus 只取三条录音
的前 20 分钟，因此不宣称复现完整 test set 分数。

## Result Ownership

| Path | Ownership |
| --- | --- |
| `<category>/audio/` | 可删除、可重建的本地 cache；`.gitignore` 忽略，不提交 |
| `<category>/*.txt`、`*.TextGrid`、`*.rttm` | committed reference；修改后同步 manifest checksum |
| `<category>/results/<audio>/` | 五份 Markdown/JSON、共享 evidence、index 与 trace 的 committed baseline |
| `metrics.json` | `evaluate.py` 从 committed results 确定性生成 |

不要手工编辑 result 或 metrics。只有完成全量 9 音频、结构审计和质量审查后才替换 committed
baseline；部分运行不得提交为新基线。

## Workflow

准备或校验音频 cache：

```bash
uv run --script platform/container/services/asr/regression/prepare.py
uv run --script platform/container/services/asr/regression/prepare.py --check
```

服务 ready 后串行刷新三类结果；`--overwrite` 只用于明确替换 committed baseline：

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

验收必须确认：9/9 trace completed、45/45 recipe completed、最终 evidence 无 error、GPU sample
无 error、结果目录 14 个产物齐全。结束后复制所需的仓库外启动/模型日志，正常停止容器，并用
`nvidia-smi` 确认 GPU 0–7 均为 0 MiB。
