# ASR Maintenance

本目录维护本地离线 ASR 的 Scheduler 与 Models 两个镜像。设计与核心诉求见
[DESIGN.md](DESIGN.md)，语料与实测结果见 [regression/AGENTS.md](regression/AGENTS.md)。

## Working Principles

1. 每套 Recipe 独立维护完整 pipeline，以可读性和单场景优化为先，允许重复代码。
2. 每个模型维护独立 Python 环境、一份启动配置，通过接口或参数支持不同场景。
3. 明确的参数、规则和映射直接写在所属代码中，一次性准备使用仓库外脚本完成。
4. 面向本地正常使用路径，失败明确报错后人工重跑，保持运行机制简单。
5. 实现文件是参数与行为的 source of truth，文档只维护职责、约束和验证入口。
6. 具体方案与参数通过实测确定；依赖满足且有资源余量的工作尽可能并发。
7. 输入适配、轨道整理和文件发布优先放在 client，server 专注规范输入上的推理流程。

## Ownership

| Path | Responsibility |
| --- | --- |
| `scheduler/api.py` | 规范音频请求、场景与 Recipe 选择、响应组装 |
| `scheduler/scenarios/<scenario>/<recipe>.py` | 本方案完整流程及其算法参数 |
| `scheduler/audio.py` | 规范音频读取、模型所需的采样转换、声道提取和裁剪 |
| `scheduler/inference.py` | 模型 HTTP 调用与固定实例容量控制 |
| `scheduler/tracing.py` | 阶段、模型调用和耗时记录 |
| `scheduler/Dockerfile` | Scheduler 独立环境与镜像 |
| `models/<model>/` | 依赖锁、权重下载、单一启动配置、推理接口和模型内部处理 |
| `models/rootfs/` | 静态 s6 graph、按环境变量选择服务的启动入口 |
| `models/Dockerfile` | 全部模型环境的安装、去重和镜像 |
| `protocol.py` | 请求与结果的数据合同 |
| `client/` | 源文件适配、轨道整理、并发提交、展示和文件发布 |
| `regression/` | 固定音频声明、reference、manifest 并发执行、评测与实测基线 |

Host、GPU、mount、secret 和网络由 Codespace 部署配置拥有。模型地址由 Scheduler 配置明确
绑定；不在 Recipe 中写容器启停或 GPU 驱动操作。

## Recipe Rules

- 每套方案有独立入口，完整拥有切窗、模型组合、调用顺序、并发、复听、裁定、speaker 与句读。
- Recipe 之间不互相调用或读取对方定稿，不要求共用 prepare、first pass、review 等阶段。
- 共用代码限于音频操作、HTTP、数据结构和 trace。场景算法留在本方案内；文件过大时拆到
  本方案目录，不建立公共 pipeline 基类、继承 hook、DAG DSL 或插件注册系统。
- 同一模型服务可以被多个 Recipe 调用。修改其默认推理行为时，验证所有受影响方案。
- 新增 Recipe 时同步显式入口映射、场景默认列表、回归选择和 CLI 输出，结果数量由所选
  Recipe 决定。省略 Recipe 列表时执行该场景登记的全部候选。
- 模型组合、切窗和参数通过本场景真实音频测试确定，设计示例不作为固定方案清单。
- 请求、Recipe、音轨、窗口和模型调用在依赖满足后尽可能并发，不增加无关的阶段等待。
  并发额度跨请求和 Recipe 共享，由 Scheduler 的固定实例容量和 serving 共同控制。
- CPU 准备和在途文件数使用固定上限，client 可重叠准备、上传与发布。静态 GPU placement
  及同卡并发安排由实测确定，以端到端耗时和吞吐验收，不强制文件或 Recipe 顺序执行。

## Model Runtime

- Models 镜像包含全部模型，`ASR_MODELS` 只选择已有 s6 服务及其依赖。graph 在构建时编译，
  运行期不生成服务定义、不安装依赖、不按请求装卸模型。
- 每个模型保留独立 `.venv` 和锁文件。容器启动与下载使用已安装环境，不解析或更新依赖；
  `uv run` 使用 `--frozen --no-sync`。
- 引擎精度、TP 和上下文等参数固定在本模型启动配置。副本复用同一配置，通过容器部署指定
  GPU 和地址，不为场景复制另一份启动脚本。
- 场景差异通过模型明确支持的 endpoint 或参数实现，分支就近写在 serving 中，不在请求中
  修改引擎全局配置。
- 模型特有提示词、上游 HTTP / SSE 协议、输出解析及必要的生成处理由本模型封装。
  Scheduler 只调用对外合同，不导入模型部署模块。
- 只下载选中模型的固定 revision；marker 命中后复用。选中模型完成加载与预热后接受请求，
  异常退出由 s6 supervision 重启。
- 权重不进入镜像，环境安装与 hardlink 去重在构建时完成。保留非 root 推理身份，secret
  使用部署注入；真实 token、机器配置、音频 cache 和模型 cache 不提交。
- Scheduler 和 Models 分别构建发布，修改 Recipe 不应触发模型环境重装或模型容器替换。

## Audio And Results

- Client 用 FFmpeg 将源文件转成规范 PCM WAV，保留需要的声道和原始时间轴；原始文件留在
  client。Scheduler 接收规范音频，Recipe 负责模型所需的采样转换、声道处理与切片。
- 输入适配和文件发布放在 client；VAD、切窗策略、模型调用和融合留在 Recipe。Scheduler
  与模型服务通过 HTTP multipart 传音频，各自管理临时文件，推理使用结束后清理。
- 模型时间相对本次输入音频，Recipe 映射回原始时间轴；句段区间包围所属 token 的实际
  时间，缺失 token 时间保持 null 并标记。local speaker 的有效范围限于该次
  调用，跨窗身份处理由本方案明确实现。
- 双人分轨输入为已同步的双声道音频，channel 0 / 1 固定对应 `S01` / `S02`，每轨独立
  识别，不运行 diarization。保留静音、原始时间和重叠讲话，按时间及轨道顺序合并。
- 两个文件或多个 audio stream 由 client 按已知映射和起点自动整理成规范输入；这是日常
  功能，不交给一次性脚本或 server。双声道文件只有显式选择分轨场景时才采用上述身份
  约定，不推测轨道身份或自动修正录制漂移。
- 结果按 `scenario/recipe` 标识，保留模型 revision、生效参数和原始 evidence；trace 记录
  调用与耗时，CLI 发布 Markdown / JSON 和可视化产物。
- 标点只允许改变标点和空白；模型改字时保留识别正文、raw 与显式 warning，不接受改写。
- 响应完整性、合法时间范围和固定并发容量属于基本正确性要求。截断文本不算成功，缺失
  时间不插值伪造；不扩展持久任务队列、自动替代模型或通用故障恢复框架。

## Validation

文档变更运行 `task check`；行为变更运行 `task check:full`。更新工具路径时同步根
`Taskfile.yaml`，不让检查遗漏 Scheduler、模型 serving 或启动脚本。

| 修改范围 | 额外验证 |
| --- | --- |
| 单套 Recipe | 对应场景真实音频、正文 / speaker / 时间指标与耗时 |
| 模型 serving、权重或启动参数 | 该模型实际接口及所有受影响 Recipe 的真实回归 |
| HTTP / 数据合同 | 调度与模型两端、CLI 输出、受影响场景 |
| Client 输入处理 | 常用文件格式、双声道 / 双文件 / 双 stream 的轨道与时间映射 |
| s6 / 启动选择 | 两种模型选择分别启动，只启动所选服务；不同模式复用同一常驻模型 |
| GPU placement | 所选模型同时驻留、实际并发与显存余量 |
| Dockerfile / 依赖 / 安装 | 对应镜像构建、环境 import、无内嵌权重、去重结果 |

以仓库根目录为 context 构建受影响镜像；共同合同变更验证两个镜像：

```bash
podman build --file platform/container/services/asr/scheduler/Dockerfile \
  --tag localhost/codespace-asr-scheduler:test .
podman build --file platform/container/services/asr/models/Dockerfile \
  --tag localhost/codespace-asr-models:test .
```

真实 GPU 验证使用 `test-asr` skill。使用本次部署所需的空闲
GPU，不停止其他任务；验证 Scheduler 重建后模型仍常驻，结束时清理本次测试容器。

回归采用日常并发路径，按场景登记的 Recipe 列表执行，不固定音频或结果数量。记录 client
准备、端到端完成与 server 推理耗时；定位问题时可单独运行 Recipe，不改变日常并发策略。
双人分轨至少有一条真实独立分轨对话，固定 checksum、轨道身份和逐轨 reference；按固定
身份评分，不通过 speaker 排列掩盖轨道交换。合成小样本只验证时间映射，不能代替真实质量回归。

不手工编辑回归结果或指标，不以模拟响应宣称质量提升。更新基线时保留可复现输入、模型
revision 和参数，未运行的方案不宣称通过。
