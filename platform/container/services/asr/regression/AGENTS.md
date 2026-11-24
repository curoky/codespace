# ASR Regression

## Scope

manifest.yaml 声明真实语料、source revision、checksum、转换、reference 与回归 Recipe；
各场景 audio 是可校验重建且不入 Git 的 cache，results 是 committed baseline。
metrics.json 由 evaluate 从结果生成，provenance.json 记录基线来源，不重复维护指标表。

## Contracts

- conversation 使用 MagicData-RAMC 双人自然对话及逐字/speaker gold reference。
- meeting 使用 AliMeeting 远场会议，正文来自官方 TextGrid；DER 使用固定
  diar-forced-alignment RTTM，保留 overlap、零 collar。
- narration 使用 LibriVox 鲁迅朗读；狂人日记 reference 校对为 audio-verbatim，
  其他保留原文底本，没有 gold speaker timing，不统计 speaker 指标。
- conversation_tracks 使用 AliMeeting R8009_M8021 的真实独立头戴麦克风轨；
  SPK8027/SPK8028 对应 channel 0/1 和 S01/S02。官方 TextGrid 转为 committed JSON，
  保留原始时间、静音与 overlap；来源、成员路径、license、checksum 由 manifest 维护。
- 混音 SA-CER/DER 可全局排列 speaker，双轨固定身份，不允许用排列掩盖轨道交换。
  双轨全局 CER 受 overlap 的时间排序影响，正文以逐轨 CER 与固定身份 SA-CER 为主；
  另逐段审计 channel/segment/token。双轨 DER 使用 transcript timing，包含段内静音，
  不与 meeting forced-alignment DER 混为同一口径。
- 双轨真实质量回归不能用复制单声道代替；合成小样本只验证时间映射。
- manifest 的 Recipe 与场景登记一致；默认执行场景全部候选，单 Recipe 仅用于定位，
  不能代替完整基线。使用日常并发路径，配置容量跨请求/Recipe 共享。
- 所有结果状态、正文、时间、unknown speaker、alignment flags、raw、revision 和参数
  都需审计。缺失 token 时间仍为 null，显式标记不能被手工修饰。
- 耗时分别记录 Client prepare/request 与 trace server/模型等待/推理；跨请求排队正常，
  并发请求耗时不可相加为批次总耗时。
- 不手工编辑结果/metrics，不用模拟响应宣称质量改善。全量场景、结构审计和质量审查
  完成后才替换 committed baseline，同时更新 provenance；实验日志放仓库外。
  当前基线是一轮实测，不证明稳定性或当前代码已验证，优化需重复场景实测。

## Validation

准备与校验 cache：

```bash
uv run --script platform/container/services/asr/regression/prepare.py
uv run --script platform/container/services/asr/regression/prepare.py --check
```

部署目标场景并检查模型 ready，再按 manifest 执行：

```bash
uv run --script platform/container/services/asr/regression/run.py \
  --scenario <scenario> --server http://127.0.0.1:18080
uv run --script platform/container/services/asr/regression/evaluate.py --markdown
```

逐场景切换部署以生成完整基线；不要向单场景部署发送缺少依赖的其他场景。
evaluate 的 Markdown 展示当前 metrics，模型 revision/参数、trace 与准备耗时保留在 results。
