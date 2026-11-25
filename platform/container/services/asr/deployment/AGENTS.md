# ASR Deployment

## Scope

拥有单场景部署输入与 GPU pipeline 示意图。模型并集、地址、容量与 placement 由场景的
`models.env`、`scheduler.yaml` 拥有，不复制参数清单；
[measurements.json](measurements.json) 保存历史资源测量与取舍，不代表当前预算或验证。

## Contracts

- 场景 environment 覆盖全部 Recipe 的模型并集，含条件复听；Scheduler 配置使用对应
  地址与固定实例容量。同一常驻模型供全部 Recipe 共享，不为方案复制模型组。
- Codespace 配置拥有 device/mount/secret/publication；将所选 environment 与对应只读
  scheduler.yaml 一起部署，不把根配置示例的全模型布局当作单场景输入。
- 手动 Podman 部署使用 test-asr Skill，Models/Scheduler 使用专用 network；模型不发布
  Host port，Scheduler 只发布 loopback。核对物理卡与容器可见编号，只注入所需 GPU，
  不为填满设备加载模型。
- [figures](figures/) 表示 HTTP 在途、实例等待与依赖，不是实测 GPU kernel 时间线；
  FireRed TP rank 属于同一实例。只展开代表性窗口，等待框不表示 GPU 内部排队。
  Recipe 依赖、容量或 placement 变化同步图；单纯 lock 变化不重画，一次性脚本不入仓库。

## Main Flows

每次只选一个场景，先核对 Recipe 模型并集与 placement，部署匹配的 Models/Scheduler，
全部模型 ready 后接受请求；切换场景先等待当前请求完成，不向当前部署提交缺依赖的场景。

## Validation

[deployment tests](../tests/) 从 Recipe 源码检查并集、environment、placement 和 Scheduler
配置。真实验证使用 test-asr Skill：同时 ready/驻留、请求重叠、显存峰值、完整结果和耗时。
单场景回归仅运行 `regression/run.py --scenario <scenario>`。
