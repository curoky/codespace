# ASR Regression

## Scope

维护可重建的真实音频语料与可审计的 committed baseline。
[manifest.yaml](manifest.yaml) 拥有 source revision、checksum、转换、reference 与回归
Recipe；场景 audio 是不入 Git 的 cache，results 是基线，
[metrics.json](metrics.json) 由 evaluate 生成，[provenance.json](provenance.json) 记录来源。

## Contracts

- conversation 使用 MagicData-RAMC 自然双人对话和逐字/speaker gold；meeting 正文来自
  AliMeeting 官方 TextGrid，DER 用固定 forced-alignment RTTM、保留 overlap、零 collar。
  narration 使用 LibriVox 鲁迅朗读，狂人日记采用 audio-verbatim，其余保留原文底本；
  没有 gold speaker timing，不统计 speaker 指标。具体 fixture 与来源由 manifest 拥有。
- conversation_tracks 使用真实独立头戴麦克风轨；manifest 的轨道身份固定对应 channel
  0/1 与 S01/S02，reference 从官方 TextGrid 转为 committed JSON，保留原始时间、静音
  和 overlap。来源、成员路径、license 与 checksum 不在文档重复。
- 混音 SA-CER/DER 可全局排列 speaker，双轨固定身份，不允许用排列掩盖轨道交换。
  双轨全局 CER 受 overlap 时间排序影响，正文以逐轨 CER 和固定身份 SA-CER 为主，另
  审计 channel/segment/token。双轨 DER 使用含段内静音的 transcript timing，不与 meeting
  forced-alignment DER 混为同一口径；真实回归不能用复制单声道代替，合成样本只验证映射。
- manifest Recipe 与场景登记一致，默认执行全部候选；单 Recipe 只用于定位，不代表完整
  基线。使用日常并发路径，配置容量跨请求/Recipe 共享。
- 审计全部结果的状态、正文、时间、unknown speaker、alignment flags、raw、revision
  和参数；缺失 token 时间保持 null，显式标记不可手工修饰。耗时区分 Client prepare/request
  与 server/模型等待/推理，跨请求排队正常，并发请求耗时不可相加为批次总耗时。
- 不手工编辑 results/metrics，不用模拟响应宣称质量改善。完整场景、结构与质量审查完成
  后才替换 committed baseline，并更新 provenance；实验日志放仓库外。一轮基线不证明
  稳定性或当前代码已验证，优化需重复场景实测。

## Main Flows

[prepare.py](prepare.py) 按 manifest 下载、转换并校验 cache；部署对应场景且模型 ready
后，[run.py](run.py) 并发调用日常 Client 生成结果；
[evaluate.py](evaluate.py) 从 reference 与结果生成 metrics。逐场景切换部署完成全量回归，
再审查结果与来源，不向单场景部署发送其他场景。

## Runtime I/O

- **Reads**：prepare 读 manifest 与已有音频；run 读场景 cache 和选择声明；evaluate 读
  manifest、reference 与 results，不将历史 metrics 当作原始输入。
- **Writes**：prepare 在 manifest 路径发布校验后的 audio，已有效 cache 直接复用；
  无效但已存在的目标需要 `--overwrite`。run 显式让 Client 覆盖场景 results 的对应输入
  目录，旧目录中的额外文件也会删除；evaluate 替换 `--output` 指定 metrics，默认写
  metrics.json，`--markdown` 同样会写文件。provenance 需在审查后同步，不由这些脚本自动更新。
- **Network**：prepare 从 manifest 指定的 Hugging Face/Internet Archive HTTPS source
  下载并跟随重定向；只提取声明的 archive member。run 向 `--server` 上传规范音频、
  文件名与识别选项；evaluate 不联网，脚本不部署模型或修改系统配置。
- **Results & Failure**：prepare 的下载目录退出时清理，转换失败或中断可遗留同级 `.partial`，
  下次准备先清理候选；通过 checksum 才替换正式音频。run 按输入发布而非整批事务，失败
  可留下新旧混合结果，不能直接认作完整基线；evaluate 输出也不提供自动回滚。

## Validation

只检查已有 cache 使用 `uv run --script platform/container/services/asr/regression/prepare.py --check`，
准备语料时去掉 `--check`。部署目标场景并确认模型 ready 后运行
`uv run --script platform/container/services/asr/regression/run.py --scenario <scenario> --server <url>`，
再用 `uv run --script platform/container/services/asr/regression/evaluate.py --markdown` 展示指标。
这些是真实下载、上传与覆盖操作，不是文档检查命令；revision、参数、trace 和准备耗时
仍保留在 results 中，不用 Markdown 指标表替代审计。
