# ASR Regression

本目录保存 ASR 的固定 9 音频 corpus、标准答案、最新 committed result 和确定性质量指标。本文
只记录当前可复现基线与操作合同；实验过程由 Git history 和仓库外原始日志承担，不在这里累积
逐轮调优记录。

## Corpus

`manifest.yaml` 是 source of truth，固定 source revision、下载 URL、checksum、转换规则、音频
属性、speaker metadata 和 reference 规则。指标单元格依次为 **CER / SA-CER / DER**，均为越低
越好；`—` 表示单 speaker fixture 不适用该指标。

| Fixture | 来源 / License | 类型 | 内容 | 时长 | 大小 | 01 Qwen fusion | 02 FireRed fusion | 03 MOSS-TD | 04 VibeVoice | 05 Qwen + Nemotron |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `conversation-weather` | [MagicData-RAMC dev](https://huggingface.co/datasets/EaseZh/magicdata_ramc/tree/79d508c3c3de40a0db55135f78113a7dfe6066d2) / CC BY-NC-ND 4.0 | 双人自然对话；gold | 天气、气候与生活体验 | 30:07.875 | 55.17 MiB | 7.89% / 9.49% / 10.60% | 7.80% / 8.84% / 10.60% | 7.79% / 7.80% / 10.60% | 9.20% / 9.19% / 10.60% | 7.92% / 20.58% / 21.83% |
| `conversation-education` | [MagicData-RAMC dev](https://huggingface.co/datasets/EaseZh/magicdata_ramc/tree/79d508c3c3de40a0db55135f78113a7dfe6066d2) / CC BY-NC-ND 4.0 | 双人自然对话；gold | 学校、专业与就业规划 | 32:18.350 | 59.15 MiB | 6.41% / 9.59% / 14.01% | 7.23% / 10.25% / 14.01% | 6.58% / 8.55% / 14.01% | 8.55% / 10.57% / 14.01% | 6.41% / 9.57% / 16.46% |
| `conversation-film` | [MagicData-RAMC dev](https://huggingface.co/datasets/EaseZh/magicdata_ramc/tree/79d508c3c3de40a0db55135f78113a7dfe6066d2) / CC BY-NC-ND 4.0 | 双人自然对话；gold | 《哪吒》剧情、票房与角色 | 30:58.400 | 56.71 MiB | 10.02% / 12.08% / 10.84% | 10.32% / 12.17% / 10.84% | 8.79% / 9.07% / 10.84% | 12.39% / 12.97% / 10.84% | 10.02% / 11.64% / 14.46% |
| `meeting-annual-event` | [AliMeeting test](https://huggingface.co/datasets/ggfox00000/dia-alimeeting-test/tree/cef2837c4a1a0762074522c1bbbbb90eb4d1acf5) / CC BY-SA 4.0 | 四人远场会议；gold | 年会、节目与抽奖安排 | 20:00.000 | 36.62 MiB | 26.57% / 40.27% / 21.28% | 34.51% / 44.82% / 21.28% | 16.33% / 60.09% / 21.28% | 32.96% / 47.78% / 21.28% | 27.01% / 34.21% / 16.22% |
| `meeting-game-launch` | [AliMeeting test](https://huggingface.co/datasets/ggfox00000/dia-alimeeting-test/tree/cef2837c4a1a0762074522c1bbbbb90eb4d1acf5) / CC BY-SA 4.0 | 四人远场会议；gold | 手游用户、奖励与卖点 | 20:00.000 | 36.62 MiB | 55.91% / 69.52% / 33.82% | 65.04% / 72.65% / 33.82% | 39.73% / 81.83% / 33.82% | 60.57% / 87.24% / 33.82% | 56.22% / 70.62% / 22.82% |
| `meeting-bike-sharing` | [AliMeeting test](https://huggingface.co/datasets/ggfox00000/dia-alimeeting-test/tree/cef2837c4a1a0762074522c1bbbbb90eb4d1acf5) / CC BY-SA 4.0 | 三人远场会议；gold | 单车停放、安全与治理 | 20:00.000 | 36.62 MiB | 14.90% / 19.07% / 10.89% | 32.34% / 36.10% / 10.89% | 12.39% / 21.46% / 10.89% | 25.82% / 52.47% / 10.89% | 15.05% / 17.54% / 14.66% |
| `narration-madmans-diary` | [LibriVox《呐喊》](https://archive.org/details/call_to_arms_jl_librivox) / Public Domain | 单人朗读；audio-verbatim | 鲁迅《狂人日记》 | 20:34.245 | 18.84 MiB | 2.49% / — / — | 2.22% / — / — | 2.89% / — / — | 2.25% / — / — | 2.49% / — / — |
| `narration-hometown` | [LibriVox《呐喊》](https://archive.org/details/call_to_arms_jl_librivox) / Public Domain | 单人朗读；source text | 鲁迅《故乡》 | 20:25.213 | 18.70 MiB | 2.15% / — / — | 1.84% / — / — | 2.97% / — / — | 3.07% / — / — | 2.15% / — / — |
| `narration-village-opera` | [LibriVox《呐喊》](https://archive.org/details/call_to_arms_jl_librivox) / Public Domain | 单人朗读；source text | 鲁迅《社戏》 | 22:20.920 | 20.46 MiB | 2.99% / — / — | 3.12% / — / — | 3.41% / — / — | 3.08% / — / — | 2.99% / — / — |

conversation 不裁切或转码。meeting 的确定性抽取由 `prepare.py` 实现。narration 评估正文区间
排除 LibriVox 开头与结尾 announcement；单 speaker 语料不计算 SA-CER 和 DER。

## Latest Baseline

本节的 9 音频 committed baseline 于 2026-10-13 从正式 image
`f6323c469e56f4bb9745731282bbfb3fe0244555f02405f2ce2f151f759b59a1`
生成，未使用代码 bind mount。image 未压缩大小为 12,370,342,156 bytes。13 个固定 model
revision marker 全部命中，模型下载阶段为 0 秒。随后部署代码重构的最终 image 为
`c7c6b7d38227dc033bdbf036debd63176e4b96b5539666407d1ee23e300a39a0`
（12,370,483,982 bytes）；该 image 完成 15/15 模型启动和真实单音频五方案 smoke，但没有重新
覆盖这组 9 音频结果。因此下列质量指标属于 committed result，不宣称由最终 image 重新生成。

### Build And Automated Tests

- `task check:full` 通过：476 项主测试、66 项 ASR 测试，以及 format、lint、type、lock、Shell
  检查。
- 正式 Dockerfile build 成功；所有模型环境从 lock 安装并完成 hardlink 去重。
- 9 份 trace 全部 `completed`，45/45 recipes 全部 `completed`。
- 12,913 个 trace events completed；2 个 VibeVoice `RepetitiveGenerationError` 按 exact-core
  拆窗恢复，最终 recipe 与 evidence 无 error。
- 1,142 组 GPU samples 无采样错误；容器没有 OOM、restart 或模型异常退出。

### Startup

冷轮指新 image 第一次创建 container rootfs，保留正常部署的持久 model-data 和 cache；热轮在
正常停止、八卡显存清零后，以同一 image、权重和 cache 再次启动。两轮都要求 15/15 实例 ready
后公开 `/health` 才成功。

| Phase | Cold | Hot |
| --- | ---: | ---: |
| image/rootfs 到 container running | 33.776 s | 0.427 s |
| container running 到公开 health | 143.165 s | 73.598 s |
| 总启动 wall | **176.941 s** | **74.026 s** |
| 模型下载 | 0 s | 0 s |

热启动与重构前 74.683 秒可比基线相当，差异为 -0.657 秒 / -0.88%，没有启动回归。冷轮长尾
仍是 FireRed TP2 的 worker/NCCL、权重加载、engine init 与 processor 初始化；不能用 lazy ready
把这些步骤转移到首请求。

最终部署重构 image 的独立热启为 74.030 秒，其中 container running 为 0.435 秒、15/15 model
ready 与公开 health 为 73.595 秒；相对上表 74.026 秒差异 0.004 秒。该轮只验证部署等价性，不与
上表冷轮混合成同一组回归数据。

### End-To-End Performance

正式 committed baseline 使用 `--parallel 1`，避免跨文件竞争污染单项质量与 trace。三批 client
wall 分别为 conversation 557.967 秒、meeting 349.741 秒、narration 376.529 秒，总计
**1,284.237 秒（21.404 分钟）**。九条 server trace 合计 1,277.783 秒，中位数 125.747 秒，
最大 196.780 秒。

| Fixture | 音频时长 | Trace wall | Trace / audio | 最终状态 |
| --- | ---: | ---: | ---: | --- |
| `conversation-weather` | 1,807.875 s | 171.556 s | 0.095× | 5/5 recipes completed |
| `conversation-education` | 1,938.350 s | 186.631 s | 0.096× | 5/5 recipes completed |
| `conversation-film` | 1,858.400 s | 196.780 s | 0.106× | 5/5 recipes completed |
| `meeting-annual-event` | 1,200.000 s | 122.856 s | 0.102× | 5/5 recipes completed |
| `meeting-game-launch` | 1,200.000 s | 124.584 s | 0.104× | 5/5 recipes completed |
| `meeting-bike-sharing` | 1,200.000 s | 100.734 s | 0.084× | 5/5 recipes completed |
| `narration-madmans-diary` | 1,234.245 s | 109.196 s | 0.088× | 5/5 recipes completed |
| `narration-hometown` | 1,225.213 s | 125.747 s | 0.103× | 5/5 recipes completed |
| `narration-village-opera` | 1,340.920 s | 139.699 s | 0.104× | 5/5 recipes completed |
| **合计** | **13,005.003 s** | **1,277.783 s** | **0.098×** | **45/45 recipes completed** |

串行质量回归中的 GPU 平均 compute busy 为 53.5%、59.8%、27.4%、17.8%、18.2%、30.2%、
2.4%、10.8%。这不是 throughput placement 评分：GPU 6 承担短 Paraformer、review Aligner 和
VibeVoice overflow，串行单文件不会主动使用 overflow。placement 的验收目标是 critical path、
phase 隔离和无 queue 回归，不是八卡平均利用率相等。

### Quality

下表来自最新 `metrics.json` 的 9-fixture macro。详细 45 项结果以该文件和
`evaluate.py --markdown` 输出为准。

| Recipe | Completed | Macro CER | Macro SA-CER | Macro DER |
| --- | ---: | ---: | ---: | ---: |
| `01-qwen-fusion` | 9/9 | 14.37% | 26.67% | 16.91% |
| `02-firered-fusion` | 9/9 | 18.27% | 30.81% | 16.91% |
| `03-moss-td` | 9/9 | **11.21%** | 31.47% | 16.91% |
| `04-vibevoice` | 9/9 | 17.54% | 36.70% | 16.91% |
| `05-qwen-nemotron` | 9/9 | 14.47% | 27.36% | 17.74% |

conversation 的最低 macro CER / SA-CER 都是 03（7.72% / 8.47%）；meeting 的最低 CER 是 03
（22.81%），最低 SA-CER 和 DER 是 05（40.79% / 17.90%）；narration 最低 CER 是 02
（2.40%）。这说明 joint ASR 的正文优势不能直接解释为 speaker 优势。

相对上一 committed baseline，最大绝对 CER / SA-CER 变化为 1.083 / 4.076 个百分点，均来自
非确定性的 `meeting-game-launch` VibeVoice 输出；DER 全部不变。其他 recipe 的细小变化来自
融合稿对非确定性联合模型证据的使用，未发现结构或协议回归。

## Result Ownership

| Path | Ownership |
| --- | --- |
| `<category>/audio/` | 可删除、可重建的本地 cache；`.gitignore` 忽略，不提交 |
| `<category>/*.txt`、`*.TextGrid` | committed reference；修改后同步 manifest checksum |
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
