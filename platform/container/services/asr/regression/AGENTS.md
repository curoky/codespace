# ASR Regression Corpus

本目录拥有普通话长音频回归集、标准答案和可复现的服务输出。大音频只按
`manifest.yaml` 下载到各题材的 `audio/` cache，不进入 Git；各题材的 `results/` 是
2026-10-10 在 5×H100 上运行五套 recipe 得到的已提交 baseline，包含 JSON、Markdown、
`evidence.json`、`trace.json` 和离线 `trace.html`。

## Corpus And Baseline

指标单元格依次为 **CER / SA-CER / DER**，均为越低越好；`—` 表示该指标不适用，
`failed` 表示服务明确返回失败，错误原因保留在对应 recipe JSON 和 `index.md`。conversation
与 meeting 使用人工 gold transcript/timing。《狂人日记》使用人工核对的 `audio_verbatim` 参考：
保留底本正字法，只校正录音中可确认的四处增字与一处省字。其余 narration 仍是公版原文的
source-text CER，可能同时反映版本、增删句和朗读差异；两者都不能与 gold CER 直接横向比较。

| Fixture | 来源 / License | 类型 | 内容 summary | 时长 | 大小 | 01 Qwen fusion | 02 FireRed fusion | 03 MOSS-TD | 04 VibeVoice | 05 Qwen + Nemotron |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `conversation-weather` | [MagicData-RAMC dev@79d508c](https://huggingface.co/datasets/EaseZh/magicdata_ramc/tree/79d508c3c3de40a0db55135f78113a7dfe6066d2) / CC BY-NC-ND 4.0 | 双人自然对话；女 + 男；gold | 南北方天气、气候变暖、穿衣和生活体验 | 30:07.875 | 55.17 MiB | 7.83% / 9.44% / 10.60% | 7.80% / 8.84% / 10.60% | 7.92% / 7.93% / 10.60% | 9.33% / 9.38% / 10.60% | 7.86% / 20.52% / 21.83% |
| `conversation-education` | [MagicData-RAMC dev@79d508c](https://huggingface.co/datasets/EaseZh/magicdata_ramc/tree/79d508c3c3de40a0db55135f78113a7dfe6066d2) / CC BY-NC-ND 4.0 | 双人自然对话；女 + 男；gold | 学校经历、专业方向、课程和就业规划 | 32:18.350 | 59.15 MiB | 6.43% / 9.60% / 14.01% | 7.23% / 10.25% / 14.01% | 6.58% / 8.55% / 14.01% | 8.69% / 10.58% / 14.01% | 6.43% / 9.59% / 16.46% |
| `conversation-film` | [MagicData-RAMC dev@79d508c](https://huggingface.co/datasets/EaseZh/magicdata_ramc/tree/79d508c3c3de40a0db55135f78113a7dfe6066d2) / CC BY-NC-ND 4.0 | 双人自然对话；女 + 男；gold | 《哪吒之魔童降世》的剧情、票房和角色 | 30:58.400 | 56.71 MiB | 10.09% / 12.15% / 10.84% | 10.32% / 12.17% / 10.84% | 8.79% / 9.07% / 10.84% | 12.82% / 13.57% / 10.84% | 10.09% / 11.71% / 14.46% |
| `meeting-annual-event` | [AliMeeting test@cef2837](https://huggingface.co/datasets/ggfox00000/dia-alimeeting-test/tree/cef2837c4a1a0762074522c1bbbbb90eb4d1acf5) / CC BY-SA 4.0 | 四人远场会议；channel 0；gold | 年会日期、节目、抽奖和员工参与安排 | 20:00.000 | 36.62 MiB | 26.70% / 40.42% / 21.28% | 34.51% / 44.82% / 21.28% | 16.56% / 72.25% / 21.28% | 33.13% / 52.98% / 21.28% | 27.06% / 34.33% / 16.22% |
| `meeting-game-launch` | [AliMeeting test@cef2837](https://huggingface.co/datasets/ggfox00000/dia-alimeeting-test/tree/cef2837c4a1a0762074522c1bbbbb90eb4d1acf5) / CC BY-SA 4.0 | 四人远场会议；channel 0；gold | 手游目标用户、使用时长、奖励机制和卖点 | 20:00.000 | 36.62 MiB | 55.93% / 69.49% / 33.82% | 64.96% / 72.70% / 33.82% | 41.01% / 88.52% / 33.82% | 60.94% / 82.03% / 33.82% | 56.23% / 70.64% / 22.82% |
| `meeting-bike-sharing` | [AliMeeting test@cef2837](https://huggingface.co/datasets/ggfox00000/dia-alimeeting-test/tree/cef2837c4a1a0762074522c1bbbbb90eb4d1acf5) / CC BY-SA 4.0 | 三人远场会议；channel 0；gold | 共享单车停放、安全、损坏和城市治理 | 20:00.000 | 36.62 MiB | 15.03% / 19.12% / 10.89% | 32.34% / 36.10% / 10.89% | 12.74% / 24.61% / 10.89% | 26.69% / 58.04% / 10.89% | 15.17% / 17.60% / 14.66% |
| `narration-madmans-diary` | [LibriVox《呐喊》](https://archive.org/details/call_to_arms_jl_librivox) / Public Domain | 单人文学朗读；audio-verbatim | 鲁迅《狂人日记》 | 20:34.245 | 18.84 MiB | 2.49% / — / — | 2.22% / — / — | 2.86% / — / — | 2.25% / — / — | 2.49% / — / — |
| `narration-hometown` | [LibriVox《呐喊》](https://archive.org/details/call_to_arms_jl_librivox) / Public Domain | 单人文学朗读；source text | 鲁迅《故乡》 | 20:25.213 | 18.70 MiB | 2.15% / — / — | 1.84% / — / — | 3.00% / — / — | 3.18% / — / — | 2.15% / — / — |
| `narration-village-opera` | [LibriVox《呐喊》](https://archive.org/details/call_to_arms_jl_librivox) / Public Domain | 单人文学朗读；source text | 鲁迅《社戏》 | 22:20.920 | 20.46 MiB | 2.97% / — / — | 3.12% / — / — | 3.39% / — / — | 3.14% / — / — | 2.97% / — / — |

`metrics.json` 保存上述逐 fixture 指标、reference quality、character accuracy、编辑计数和按题材
聚合值。评估前删除圈号脚注 marker，避免 NFKC 把其折叠为虚假的数字正文。当前
baseline 使用 image `localhost/codespace-asr:alignment-optimization-final-v2`，与同一提交中的
ASR server code 配套。baseline 中 45/45 个 recipe completed；未来出现失败时仍应作为回归
结果保留，不得删除、用其他 recipe 补值或把缺失指标记为 0。

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
