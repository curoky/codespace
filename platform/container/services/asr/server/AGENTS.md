# ASR Server

`api.py` 仅处理文件上传、状态与产物；`jobs.py` 管理文件队列和重启恢复；
`recipes.py` 是五套固定流程，`transcript.py` 处理保守选择、时间与 speaker 映射。
运维代码属于相邻 `ops/`。本层只通过各模型目录的 client 调 HTTP，不导入模型 SDK。

`run` 是 server 的 Shell 启动入口；s6 定义集中在
[`rootfs/etc/s6/s6-rc.d/asr-server/`](../rootfs/etc/s6/s6-rc.d/asr-server/)，只负责
日志、环境和 x 用户切换。server 环境在镜像构建时安装，模型脚本通过 `uv run` 自动
创建或同步各自的环境。

Server 必须单进程，不能增加 uvicorn workers。`server.yaml` 由 Pydantic 严格校验。
image 的数据目录固定为 `/data/asr`，Host 路径通过 volume 映射；不要只改 server 的
data_dir 而让 SDK 服务无法读取切片。监听参数在 `server/run`，CLI 默认地址同步维护。
每个 job 的计算缓存受模型脚本、锁文件、有效输入内容和参数约束；音频文件名不作为
内容标识。失败的请求不缓存，取消请求必须释放模型锁。部署改变后不恢复旧 job。

同一文件固定五套输出。模型失败保留其他可完成方案；缺少旁路校验时明确标记，
不覆盖成功的联合稿。`separate_channels` 逐声道执行并合并为五套产物，不额外增加
方案。不要把完成的 HTTP 调用等同于识别正确：截断、结构错误、越界时间必须检查。

标点恢复只允许标点变化；数字、大小写、空格和口语内容不可改写。对齐失败用 null，
不能插值补时间；不把候选置信度跨模型平均。修改融合或边界处理时补充行为测试。

## Pipeline Invariants

- 同文件先 prepare、四路 first_pass，再依次执行五套方案。`prepare` 先跑全文件 pyannote，
  再取 VAD 与 speaker 活动并集。短窗按同一原音与 padding 提供给各路候选，不能互喂答案。
- 只有分歧、空识别或异常重复触发扩窗复听。先听 Qwen / FireRed / Whisper，仍未解决才
  调 MOSS-Audio。同模型重复采样与同家族不增加独立票数；两份融合稿不能读取对方定稿。
- 文字替换要求主模型复听也改口且独立家族支持。数值、热词、英文专名启发式和多人
  活动窗口受保护；这不是完整实体识别。保留 raw、候选、复核依据和未解决标记。
- 联合模型按长窗输出自身正文、时间和局部 speaker。用 pyannote 单人活动映射到全文
  身份，不能按同名局部标签拼接。歧义保持未知。四路校验只提供分歧标记，不改写联合稿。
- 联合窗口的结构、时间范围与活动尾部须校验；失败最多缩窗重试两层。尾部覆盖是
  漏转启发式，不是全文完整性证明。按字词时间裁剪核心区间，边界无法对齐则失败。
- 全部时间还原为原音整数毫秒；speaker 可多人或未知，同一句正文不因多人标签重复。
  各方案的 speaker 标签不能直接互认，更不能跨文件识别人名。
- 第五稿依赖第一稿文字与时间，只用 Nemotron 重标 speaker。已知全文超过 8 人时失败，
  未知人数标 `unverified_max_8`，pyannote 观察到超限标 `suspected_out_of_scope`。
