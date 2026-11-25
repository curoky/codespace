# ASR Regression

## Scope

[manifest.yaml](manifest.yaml) 拥有真实语料来源/revision/checksum/转换/reference/Recipe；
audio 是可重建、不入 Git 的 cache，results 是 committed baseline，
[metrics.json](metrics.json) 由 evaluate 生成，[provenance.json](provenance.json) 记录来源。
准备、执行、评分分别见 [prepare.py](prepare.py)、[run.py](run.py)、[evaluate.py](evaluate.py)。

## Contracts

- reference 口径以 manifest 为准，区分 audio-verbatim 与原文底本；narration 无 gold
  speaker timing，不统计 speaker 指标。meeting 使用官方 TextGrid 正文与固定
  forced-alignment RTTM，DER 保留 overlap、零 collar；conversation 使用逐字/speaker gold。
- 双轨用真实独立头戴麦克风与官方时间 reference，身份固定对应 channel 0/1/S01/S02，
  保留静音/overlap；不能用复制单声道替代质量回归，合成样本只检查时间映射。
- 混音 SA-CER/DER 可全局排列 speaker，双轨不可排列掩盖轨道交换；双轨正文以逐轨 CER/
  固定身份 SA-CER 为主并审计 channel/segment/token，全局 CER 受 overlap 排序影响。
  双轨 DER 来自含段内静音的 transcript timing，不与 meeting 的口径混同。
- manifest 与场景登记一致，完整基线执行全部候选并使用日常共享容量并发路径；单 Recipe
  只定位问题。审计状态/正文/时间/unknown speaker/flags/raw/revision/参数，null/标记不修饰。
  区分 Client prepare/request 与 server/模型等待/推理，并发耗时不能相加为批次耗时。
- 不手工编辑 results/metrics 或用模拟响应证明质量；全场景结构/质量审查后才替换基线并
  更新 provenance，实验日志在仓库外。一轮实测不证明稳定性/当前代码，优化需重复实测。

## Runtime I/O

- **Reads**：prepare 读 manifest/已有 audio，run 读场景 cache/选择，evaluate 读 manifest、
  reference/results，不用历史 metrics 评分。
- **Writes**：prepare 在 manifest 路径发布校验后的 audio，有效 cache 复用，无效旧目标
  要求 `--overwrite`；run 让 Client 删除并替换对应输入的结果目录，evaluate 替换 `--output`
  指定 metrics，`--markdown` 仍写文件。provenance 在审查后同步，不由脚本自动生成。
- **Network**：prepare 从 manifest 的 Hugging Face/Internet Archive HTTPS source 下载并
  跟随重定向，仅提取声明 member；run 向 `--server` 上传音频/文件名/选项，evaluate 离线。
  脚本不部署模型或修改系统配置。
- **Results & Failure**：prepare 校验后才替换 audio，下载目录退出清理，转换失败/中断可
  遗留同级 `.partial`，下次准备清理候选。run 非整批事务，失败可留下新旧混合结果；
  evaluate 无自动回滚，不能把部分产物当完整基线。

## Validation

prepare 的 `--check` 只查已有 cache；实际回归先部署匹配场景并确认 ready，再执行 run
的 `--scenario`/`--server`，evaluate 展示指标。逐场景切换完成全量基线，revision/参数/
trace/准备耗时保留在 results 中。下载、上传和结果覆盖都是显式操作，不用于文档检查。
