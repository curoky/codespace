# ASR Regression Corpus

本目录拥有普通话长音频回归集、标准答案和可复现的服务输出。大音频只按
`manifest.yaml` 下载到各题材的 `audio/` cache，不进入 Git；各题材的 `results/` 是
2026-10-09 在 5×H100 上运行五套 recipe 得到的已提交 baseline，包含 JSON、Markdown、
`evidence.json`、`trace.json` 和离线 `trace.html`。

## Corpus And Baseline

指标单元格依次为 **CER / SA-CER / DER**，均为越低越好；`—` 表示该指标不适用，
`failed` 表示服务明确返回失败，错误原因保留在对应 recipe JSON 和 `index.md`。conversation
与 meeting 使用人工 gold transcript/timing。《狂人日记》使用人工核对的 `audio_verbatim` 参考：
保留底本正字法，只校正录音中可确认的四处增字与一处省字。其余 narration 仍是公版原文的
source-text CER，可能同时反映版本、增删句和朗读差异；两者都不能与 gold CER 直接横向比较。

| Fixture | 来源 / License | 类型 | 内容 summary | 时长 | 大小 | 01 Qwen fusion | 02 FireRed fusion | 03 MOSS-TD | 04 VibeVoice | 05 Qwen + Nemotron |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `conversation-weather` | [MagicData-RAMC dev@79d508c](https://huggingface.co/datasets/EaseZh/magicdata_ramc/tree/79d508c3c3de40a0db55135f78113a7dfe6066d2) / CC BY-NC-ND 4.0 | 双人自然对话；女 + 男；gold | 南北方天气、气候变暖、穿衣和生活体验 | 30:07.875 | 55.17 MiB | 7.96% / 9.57% / 10.60% | 7.80% / 8.84% / 10.60% | 8.23% / 8.25% / 10.60% | failed | 7.99% / 20.68% / 21.83% |
| `conversation-education` | [MagicData-RAMC dev@79d508c](https://huggingface.co/datasets/EaseZh/magicdata_ramc/tree/79d508c3c3de40a0db55135f78113a7dfe6066d2) / CC BY-NC-ND 4.0 | 双人自然对话；女 + 男；gold | 学校经历、专业方向、课程和就业规划 | 32:18.350 | 59.15 MiB | 6.54% / 9.72% / 14.01% | 7.23% / 10.25% / 14.01% | 6.79% / 8.68% / 14.01% | 9.08% / 11.12% / 14.01% | 6.54% / 9.70% / 16.46% |
| `conversation-film` | [MagicData-RAMC dev@79d508c](https://huggingface.co/datasets/EaseZh/magicdata_ramc/tree/79d508c3c3de40a0db55135f78113a7dfe6066d2) / CC BY-NC-ND 4.0 | 双人自然对话；女 + 男；gold | 《哪吒之魔童降世》的剧情、票房和角色 | 30:58.400 | 56.71 MiB | 10.36% / 12.44% / 10.84% | 10.32% / 12.17% / 10.84% | 9.11% / 9.41% / 10.84% | 12.88% / 13.50% / 10.84% | 10.36% / 11.99% / 14.46% |
| `meeting-annual-event` | [AliMeeting test@cef2837](https://huggingface.co/datasets/ggfox00000/dia-alimeeting-test/tree/cef2837c4a1a0762074522c1bbbbb90eb4d1acf5) / CC BY-SA 4.0 | 四人远场会议；channel 0；gold | 年会日期、节目、抽奖和员工参与安排 | 20:00.000 | 36.62 MiB | 26.72% / 40.43% / 21.28% | failed | 17.60% / 72.99% / 21.28% | failed | 27.05% / 34.33% / 16.22% |
| `meeting-game-launch` | [AliMeeting test@cef2837](https://huggingface.co/datasets/ggfox00000/dia-alimeeting-test/tree/cef2837c4a1a0762074522c1bbbbb90eb4d1acf5) / CC BY-SA 4.0 | 四人远场会议；channel 0；gold | 手游目标用户、使用时长、奖励机制和卖点 | 20:00.000 | 36.62 MiB | failed | failed | failed | failed | failed |
| `meeting-bike-sharing` | [AliMeeting test@cef2837](https://huggingface.co/datasets/ggfox00000/dia-alimeeting-test/tree/cef2837c4a1a0762074522c1bbbbb90eb4d1acf5) / CC BY-SA 4.0 | 三人远场会议；channel 0；gold | 共享单车停放、安全、损坏和城市治理 | 20:00.000 | 36.62 MiB | 15.08% / 19.21% / 10.89% | failed | failed | failed | 15.22% / 17.69% / 14.66% |
| `narration-madmans-diary` | [LibriVox《呐喊》](https://archive.org/details/call_to_arms_jl_librivox) / Public Domain | 单人文学朗读；audio-verbatim | 鲁迅《狂人日记》 | 20:34.245 | 18.84 MiB | 2.64% / — / — | 2.22% / — / — | 2.91% / — / — | 2.35% / — / — | 2.64% / — / — |
| `narration-hometown` | [LibriVox《呐喊》](https://archive.org/details/call_to_arms_jl_librivox) / Public Domain | 单人文学朗读；source text | 鲁迅《故乡》 | 20:25.213 | 18.70 MiB | 2.22% / — / — | 1.84% / — / — | failed | failed | 2.22% / — / — |
| `narration-village-opera` | [LibriVox《呐喊》](https://archive.org/details/call_to_arms_jl_librivox) / Public Domain | 单人文学朗读；source text | 鲁迅《社戏》 | 22:20.920 | 20.46 MiB | 3.14% / — / — | 3.12% / — / — | 3.39% / — / — | 3.10% / — / — | 3.14% / — / — |

`metrics.json` 保存上述逐 fixture 指标、reference quality、character accuracy、编辑计数和按题材
聚合值。评估前删除圈号脚注 marker，避免 NFKC 把其折叠为虚假的数字正文。当前
baseline 使用 image `localhost/codespace-asr:speaker-point-fix`，其 ASR server code 与
commit `45652ed` 一致。baseline 中 32/45 个 recipe completed；失败也是回归结果，不得删除、
用其他 recipe 补值或把缺失指标记为 0。

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
