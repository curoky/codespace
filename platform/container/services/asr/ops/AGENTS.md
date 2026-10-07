# ASR Operations

`scheduler.py` 独占管理本 ASR 容器的模型资源。可见 GPU 池只影响并行度；每模型一个
实例、一个在途请求，FIFO 等待资源，无请求的模型在需要资源时才被回收。CPU 请求
绕过 GPU inventory 和 FIFO，只使用本模型锁与 CPU semaphore。
不停止外部进程，不固定物理卡号，不降级模型或跳过方案。

模型 client 提供固定 `URL` 与 `infer(http, request)`，scheduler 不生成或下发监听参数。
启动前只向 GPU 模型的 `/run/asr/<model>/CUDA_VISIBLE_DEVICES` 写入已预留设备的 UUID；
CPU 模型不写环境文件。音频路径遵循根目录 AGENTS 的 image 契约。

`processes.py` 负责有超时的子进程与 GPU inventory，并调用
[`asr-model-service`](../rootfs/usr/local/bin/asr-model-service) 请求启停。该脚本只接受
固定 s6 graph 中 ASR 服务的 start / stop，随 rootfs 安装为 root-owned
`/usr/local/bin/asr-model-service`；[sudoers](../rootfs/etc/sudoers.d/asr) 只授权 x 调用
这个入口。s6 定义统一存放在 `rootfs/etc/s6/s6-rc.d/`。
原因是 shared runtime 的 s6 live state 由 root 管理，而 HTTP server 以 x 运行；
不修改 shared runtime 权限，也不另造管理 RPC。s6 的排他锁由 `s6-rc -b` 自己管理。

停止由 s6 发 TERM；`timeout-kill` / `flag-timeout-killpg` 超时终止进程组。模型 run
退出后，`finish` 以 x 清理残留 engine 子进程，同样覆盖异常退出。启停脚本通过
`s6-svc -wD` 等待 run 和 finish 结束，之后才释放 GPU；操作失败保留预留。
Server 重启先停止本容器模型、重建资源记录，不恢复文件请求。

独立排查模型时先停止对应任务，然后在模型目录运行 `download_model.sh`、`run`，
两个脚本都会自动同步本模型环境。脚本参数可就地阅读。只手动启停 s6 而不通知运行中的
调度器会破坏其资源记录，日常统一由 server 按需控制。
