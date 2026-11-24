# ASR Deployment

## Scope

维护单场景部署输入与 GPU pipeline 示意图。模型集合、地址、容量和 placement 以每个
场景的 models.env/scheduler.yaml 为准，不在文档复制清单。历史资源测量与性能取舍见
`measurements.json`，不作为当前预算或验证结论。

## Contracts

- models.env 覆盖场景全部 Recipe 的模型并集，scheduler.yaml 使用对应模型地址与固定实例
  容量；条件复听也属于依赖。每次只选一个场景，全部模型 ready 后接受请求。
- 同一常驻模型供全部 Recipe 共享，不为方案复制模型组；切换场景先等待当前请求完成。
- Codespace 配置拥有 device/mount/secret/publication；将所选 models.env 的 environment
  及对应只读 scheduler.yaml 一起部署，不把 config.example.yaml 的全模型布局当单场景配置。
- 手动 Podman 部署使用 test-asr Skill，Models 与 Scheduler 使用专用 network；
  模型不发布 Host port，Scheduler 只发布 loopback。核对物理卡与容器可见 GPU 编号，
  只注入 placement 所需设备，不为填满设备加载模型。
- figures 的 PNG/SVG 表示 HTTP 在途、实例等待与依赖，不是实测 GPU kernel 时间线；
  FireRed TP rank 属于同一实例。Recipe 依赖、容量或 placement 改变时更新对应图，
  单纯 lock 版本变化不要求重画；一次性生成脚本不入仓库。

图索引：`figures/{narration,conversation_tracks,conversation,meeting}-timeline.{png,svg}`。
图只展开代表性窗口，真实请求会重复调用；等待框不代表 GPU 内部排队。

## Validation

deployment tests 从 Recipe 源码检查并集、environment、placement 与 Scheduler 配置。
真实验证使用 test-asr Skill：所选模型同时 ready/驻留、请求重叠、显存峰值、完整结果与耗时。
单场景部署仅执行 `regression/run.py --scenario <scenario>`，不提交其他场景。
