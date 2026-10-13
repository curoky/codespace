# ASR Regression

`manifest.yaml` 声明真实语料、固定 source revision、checksum、转换规则、逐字 reference
和每个场景实际执行的 Recipe。音频 cache 位于 `<scenario>/audio/`，不入 Git。

## Corpus And Scoring

- `conversation`：MagicData-RAMC 的三条双人自然对话，逐字与 speaker gold reference。
- `meeting`：AliMeeting 三条远场会议前 20 分钟；正文使用官方 TextGrid，DER 使用固定
  `diar-forced-alignment` revision 的 RTTM，保留 overlap，collar 为零。
- `narration`：三条 LibriVox 鲁迅朗读，《狂人日记》使用已校对的 audio-verbatim reference，
  其余采用原文底本；没有 gold speaker timing，因此只统计正文 CER。
- `conversation_tracks`：AliMeeting R8009_M8021 前 20 分钟真实双人头戴麦克风录音，
  SPK8027 / SPK8028 对应 channel 0 / 1，固定为 S01 / S02。官方 TextGrid 预处理成
  `conversation_tracks/R8009_M8021.json`，保留原始时间、独立身份、静音和 overlap。
  来源、成员路径、license 和 checksum 都在 manifest；一次性预处理脚本不入 Git。

普通混音场景的 SA-CER / DER 允许全局 speaker 排列；双轨评分固定身份，不允许排列。
双轨时间排序的全局 CER 会受同时讲话的段落排序影响，正文质量以逐轨 CER 和固定身份
SA-CER 为主；固定身份检查另外逐段验证 channel / segment / token 一致性。
`per_speaker_cer` 分别记录两轨 CER，`fixed_speaker_cer` 能检测左右轨交换。双轨 DER 使用
原始 transcript segment timing，包含段内静音，不将该值与 meeting 的 forced-alignment
DER 混为同一口径。

## Ownership

| Path | Responsibility |
| --- | --- |
| `manifest.yaml` | 输入、reference 与回归 Recipe 的 source of truth |
| `<scenario>/audio/` | 可删除、可校验重建的本地 cache |
| `<scenario>/*.txt`, `*.TextGrid`, `*.rttm`, `*.json` | committed reference |
| `<scenario>/results/<audio>/` | 本场景各 Recipe Markdown / JSON、evidence、trace 与 index |
| `metrics.json` | evaluate 从当前结果确定性生成的指标 |

不要手工编辑结果或指标。只有全量场景运行、结构审计和质量审查完成后才替换 committed
baseline。实验日志放仓库外；不得用模拟结果宣称质量改善。

## Workflow

```bash
uv run --script platform/container/services/asr/regression/prepare.py
uv run --script platform/container/services/asr/regression/prepare.py --check
```

服务和所需模型 ready 后，读取 manifest 的人数与 Recipe，按两个文件并发执行：

```bash
uv run --script platform/container/services/asr/regression/run.py \
  --server http://127.0.0.1:18080
uv run --script platform/container/services/asr/regression/evaluate.py --markdown
```

`run.py --scenario <scenario>` 用于受影响场景回归。manifest 的 `recipes` 与实际登记保持
一致；CLI 省略 `--recipe` 执行场景全部方案，定点测试可以选择一套，但不代替完整基线。
结果文件名以 `<scenario>--<recipe>` 发布，结果数量由所选 Recipe 决定。

审计所有返回状态、正文、时间范围、unknown speaker、alignment flags、raw evidence 与
模型 revision。耗时来自 client evidence 的准备和端到端完成，以及 trace 的 server
总耗时、每模型等待和推理阶段；跨请求并发导致等待属于正常容量约束。

## Baseline

以下结果来自最终两镜像部署，按 manifest 执行所有 Recipe；client 同时处理两条录音，
实例额度跨请求与 Recipe 共享。模型 revision 和实际参数保存在各结果的 evidence 中。
CER / SA-CER / DER 均为越低越好，`—` 表示该语料没有对应 gold 指标。


| Fixture | Recipe | CER | SA-CER | DER |
| --- | --- | ---: | ---: | ---: |
| conversation-weather | conversation/moss_joint | 7.61% | 7.61% | 6.15% |
| conversation-weather | conversation/qwen_pyannote | 8.15% | 9.74% | 10.60% |
| conversation-weather | conversation/vibevoice | 9.14% | 9.13% | 13.84% |
| conversation-education | conversation/moss_joint | 6.04% | 8.11% | 12.39% |
| conversation-education | conversation/qwen_pyannote | 6.35% | 9.50% | 14.01% |
| conversation-education | conversation/vibevoice | 8.52% | 10.53% | 24.02% |
| conversation-film | conversation/moss_joint | 7.96% | 8.23% | 5.85% |
| conversation-film | conversation/qwen_pyannote | 10.25% | 12.29% | 10.84% |
| conversation-film | conversation/vibevoice | 12.02% | 12.24% | 16.83% |
| meeting-annual-event | meeting/moss_joint | 15.65% | 11.48% | 18.41% |
| meeting-annual-event | meeting/qwen_nemotron | 26.20% | 33.50% | 8.96% |
| meeting-annual-event | meeting/vibevoice | 34.15% | 35.11% | 35.74% |
| meeting-game-launch | meeting/moss_joint | 38.89% | 31.85% | 30.76% |
| meeting-game-launch | meeting/qwen_nemotron | 55.96% | 70.53% | 20.29% |
| meeting-game-launch | meeting/vibevoice | 62.46% | 82.34% | 78.42% |
| meeting-bike-sharing | meeting/moss_joint | 12.90% | 9.92% | 18.15% |
| meeting-bike-sharing | meeting/qwen_nemotron | 16.50% | 19.32% | 5.69% |
| meeting-bike-sharing | meeting/vibevoice | 28.89% | 46.62% | 37.18% |
| narration-madmans-diary | narration/qwen | 2.62% | — | — |
| narration-madmans-diary | narration/firered | 2.20% | — | — |
| narration-hometown | narration/qwen | 2.22% | — | — |
| narration-hometown | narration/firered | 1.89% | — | — |
| narration-village-opera | narration/qwen | 3.01% | — | — |
| narration-village-opera | narration/firered | 3.10% | — | — |
| conversation-tracks-childrens-day | conversation_tracks/qwen | 13.89% | 4.44% | 10.59% |
| conversation-tracks-childrens-day | conversation_tracks/firered | 13.61% | 4.02% | 10.59% |


Client request 包含准备、上传和等待响应，Server 来自 trace；同时运行两个录音，不能将这些耗时相加当作批次总耗时。

| Fixture | Prepare (s) | Request (s) | Server (s) |
| --- | ---: | ---: | ---: |
| conversation-weather | 0.32 | 160.67 | 160.00 |
| conversation-education | 0.36 | 205.59 | 204.86 |
| conversation-film | 0.32 | 158.03 | 157.23 |
| meeting-annual-event | 0.29 | 129.92 | 129.40 |
| meeting-game-launch | 0.22 | 90.78 | 90.35 |
| meeting-bike-sharing | 0.22 | 94.13 | 93.68 |
| narration-madmans-diary | 0.98 | 115.83 | 114.47 |
| narration-hometown | 0.98 | 126.92 | 125.53 |
| narration-village-opera | 1.06 | 175.83 | 174.37 |
| conversation-tracks-childrens-day | 0.28 | 178.42 | 177.51 |

双轨逐轨 CER：

| Recipe | S01 | S02 |
| --- | ---: | ---: |
| conversation_tracks/qwen | 5.43% | 3.63% |
| conversation_tracks/firered | 5.29% | 2.98% |

全部结果状态、区间、模型 revision、参数与双轨固定身份已审计通过。原始 token 的缺失时间仍保持 null；alignment、unknown speaker 和标点改字拒绝均保留为显式标记。

| Recipe | Segments | Alignment flags | Unknown speaker flags |
| --- | ---: | ---: | ---: |
| conversation/moss_joint | 1461 | 0 | 0 |
| conversation/qwen_pyannote | 1213 | 179 | 74 |
| conversation/vibevoice | 797 | 0 | 0 |
| conversation_tracks/firered | 375 | 10 | 0 |
| conversation_tracks/qwen | 370 | 3 | 0 |
| meeting/moss_joint | 1505 | 0 | 0 |
| meeting/qwen_nemotron | 3223 | 2479 | 231 |
| meeting/vibevoice | 749 | 0 | 67 |
| narration/firered | 306 | 2 | 0 |
| narration/qwen | 305 | 0 | 0 |

双轨全局 CER 受重叠发言的时间排序影响，正文质量以逐轨 CER 和固定身份 SA-CER 为主要依据。两套分轨方案使用相同 VAD，因此本次 DER 相同；该值评价语音时间范围，不表示运行了 diarization。

并发 trace 审查确认：Qwen、FireRed、MOSS-audio、VibeVoice 的实际在途推理达到各两路，其余模型不超过各自固定额度；检查区间边界时允许独立毫秒取整的误差。全部混录 joint 生成调用在 speaker anchor 完成前提交，实际开跑仍受跨请求共享额度约束。

在本 corpus 中，MOSS joint 的混录正文优于其他候选，Nemotron 的远场 DER 较低；VibeVoice 的远场正文和 speaker 指标较弱，Qwen 融合在远场重叠讲话中仍有较多 alignment 标记。候选彼此独立，保留当前实测差异，后续升级按对应场景重新评测。

## Validation Provenance

本次基线于 2026-10-13 从两个完整构建的镜像生成，未使用代码 bind mount：

- Models：`f9536a57c774b0f010043122086ffc45f1469882c1848b4961f87f1edd3986a7`。
- Scheduler：`10106247ccb066bb990079b4438cf121466cd8432dd17dace0d3f35aae48098b`。

`task check:full` 通过，包括 47 项 ASR 测试、446 项控制面测试及格式、lint、类型、锁文件和
Shell 检查。两个镜像构建通过；完整模型集合与 CPU VAD / Punc 子集分别验证了静态 s6 选择
启动。全部 13 个模型服务 ready，替换 Scheduler 时 Models 启动时间与常驻进程保持。
10 条真实录音、26 份结果全部完成，状态、时间范围、revision、参数和双轨身份审计通过。
本次验证容器与专用网络已清理，GPU 0–7 显存使用均回到 0 MiB。

当前指标来自一轮真实回归；稳定性和参数优化通过对应场景的重复实测确认。
