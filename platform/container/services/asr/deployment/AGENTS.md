# ASR Deployment

## Scope

拥有单场景部署输入与 GPU pipeline 图；模型/地址/容量/placement 以场景的 models.env
和 scheduler.yaml 为准。[measurements.json](measurements.json) 是历史数据，不代表当前
预算或验证结论。

## Contracts

- 每次只部署一个场景的全部 Recipe 模型并集，含条件复听；常驻实例共享、不为方案复制
  模型组，全部加载/预热 ready 后接收请求。切换前等待当前请求结束，不提交缺依赖的场景。
- 将对应 environment 与只读 scheduler.yaml 一起部署；device/mount/secret/publication
  属于 Codespace 配置，不把全模型示例当单场景输入。
- 手动部署使用 test-asr Skill；Models/Scheduler 用专用 network，模型不发布 Host port，
  Scheduler 只发布 loopback。核对物理卡/容器 GPU 编号，只注入所需设备，不为填满卡加载模型。
- [figures](figures/) 表示代表性窗口的 HTTP 在途/实例等待/依赖，不是实测 GPU kernel
  时间线或内部排队，TP rank 属于同一实例；依赖/容量/placement 变化同步图，单纯 lock
  变化不重画，一次性生成脚本不入仓库。

## Validation

[tests](../tests/) 检查 Recipe 并集/environment/placement/Scheduler 配置；真实验证检查
同时 ready/驻留、请求重叠、显存峰值、完整结果与耗时。仅提交
[regression/run.py](../regression/run.py) 的对应场景，不用静态图或配置测试替代实测。
