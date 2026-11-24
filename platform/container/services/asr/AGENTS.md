# ASR

## Scope

维护离线录音的 Scheduler 与 Models 两个独立镜像，覆盖朗读、双人混录、同步双人分轨、
多人会议。每场景选择一套或多套 Recipe，独立输出正文、时间、speaker、evidence 和 trace；
质量、模型组合与参数由真实音频确定，不从名称推断排名。

Scheduler 拥有 API、Recipe、音频操作、HTTP 容量和 trace；Models 拥有各模型环境、权重、
serving 与静态 s6；Client 拥有文件适配、轨道整理与发布。`protocol.py` 定义数据合同，
`execution.py` 只提供任务收敛与文件线程生命周期，不包含算法。Host/GPU/mount/secret/
network 属于部署输入，Scheduler 不启停模型，Models 不选择 Recipe。

## Contracts

- 每套 Recipe 完整拥有切窗、组合、调用顺序、并发、复听、裁定、speaker 和句读，允许重复。
  Recipe 不互调或读取对方定稿，不要求共同 prepare/first-pass/review；大文件只拆入本方案
  目录，不增加公共 pipeline 基类、hook、DAG DSL 或插件框架。
- 共用代码仅限音频操作、HTTP、数据结构、trace 与 execution。算法参数直接写在所属 Recipe，
  模型提示词、上游协议、输出解析与生成处理留在该模型 serving；Scheduler 不导入部署模块。
- 新 Recipe 同步显式入口、场景默认列表、回归选择与 CLI 输出。省略列表执行场景全部候选，
  结果数量由选择决定；同一模型默认行为变化须覆盖所有受影响 Recipe。
- 请求、Recipe、轨道、窗口及模型调用只等待真实依赖或容量；固定实例额度跨请求/Recipe
  共享，不增加 GPU 级互斥。CPU 准备与在途文件数有界，Client 准备、上传、发布可重叠。
  同卡并发与 placement 以端到端完成时间、吞吐和显存峰值验收。
- 通过 TaskGroup/collect 收敛子任务；失败或取消先等待所有文件使用者退出，再删除临时目录。
  文件/推理线程通过 blocking 等待完成，不能只取消包装协程后释放文件或容量。
- Models 包含全部模型，各自独立 .venv/lock 和单一启动配置；ASR_MODELS 只选择已编译 s6
  服务及依赖。运行期不生成 graph、安装依赖或按请求装卸模型，uv 使用 frozen/no-sync。
- 引擎精度、TP、上下文等固定在本模型启动配置；副本复用配置，以容器分配 GPU/地址。
  场景差异通过显式 endpoint/参数实现，不修改引擎全局状态或透传任意引擎配置。
- 选中模型只下载固定 revision，marker 命中复用；全部加载/预热完成再提交推理，
  异常退出由 s6 supervision 重启。权重/cache 不入镜像，构建期安装环境并 hardlink 去重，
  保留非 root 推理与部署 secret。
- 每次部署一个场景的全部 Recipe 模型并集，含条件复听模型；请求期间常驻，切换配置前
  等待当前请求结束。Scheduler 独立构建发布，重建不替换 Models 或重装模型环境。
- Client 用 FFmpeg 转成规范 PCM WAV，保留原始时间轴和所需声道，不提前混音、删静音或
  复制模型前处理。Scheduler/Models 用 multipart 传音频，各自管理临时文件，无共享请求目录。
- 分轨输入须已同步，channel 0/1 固定 S01/S02，各轨独立识别且不运行 diarization，按时间/
  轨道排序并保留 overlap。双文件/多 stream 由 Client 按显式映射和起点整理；仅选择分轨
  场景才赋予该身份，不猜测串音、身份或修正录制漂移。
- 模型时间相对输入，Recipe 映射回原始时间轴；local speaker 仅在本次调用有效。
  segment 包围 token 实际区间，缺失时间保留 null 并标记，不插值伪造。
- 结果以 scenario/recipe 标识，保留 revision、生效参数、raw evidence 与 trace。
  标点只能改变标点/空白；改字保留正文和 warning。截断正文不算成功。
- 正常路径是模型 ready 后提交完整文件，失败明确报错后人工重跑；不扩展持久队列、
  自动替代模型、断点恢复或通用重试/故障恢复框架。固定准备/revision/参数不保证 GPU 逐位一致。

## Pitfalls

- Scheduler health 只表示 API 可用，不能代替所选模型 health；调用方必须匹配当前部署场景。
- memory utilization 不是进程显存硬上限；ready 占用不是运行峰值或 checkpoint 大小。
  .venv 逻辑大小含重复 hardlink，不能累加推算 image 物理占用。历史数据见
  `deployment/measurements.json`，当前参数以 run/serving/config 为准。

## Validation

通用检查遵循根文档，Client 测试需要 FFmpeg。Recipe 变化验证对应真实场景；serving/
HTTP/协议变化验证两端、CLI 和全部受影响 Recipe；输入适配验证格式、轨道与时间映射。
s6 变化验证不同模型选择只启动目标及依赖，模型支持的模式复用同一进程。

artifact/依赖变化构建对应 Dockerfile，检查环境 import、无权重和 hardlink 去重；协议或
execution 变化检查两个镜像。构建 context 为仓库根，GPU 与真实音频操作使用 test-asr Skill，
部署合同见 `deployment/AGENTS.md`，语料和评分见 `regression/AGENTS.md`。
不停止其他任务，只清理本次验证容器；未运行的验证不得宣称通过。
