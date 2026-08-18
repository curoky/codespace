# Codespace Sidecar 约束

本目录保存 Codespace host 级共享服务的容器资产。

## 定义

每个已配置 host 只有一个 sidecar container，服务该 host 上的全部开发环境，不属于任何
project 或 instance。当前共享服务是 Atuin server 和 image-prewarm 定时任务。

这里的 sidecar 表示它与一组 Codespace environment 的关系，不是每个 environment 各自
附带的 companion container。

## 不变量

- 每个 host 最多存在一个 Codespace sidecar。
- 共享服务只能通过 host loopback 暴露：Linux 使用 host network；macOS Podman Machine
  使用 bridge network，并仅向 loopback publish 端口。
- Sidecar identity 只由 host 决定，不包含 project 或 instance ID。
- Sidecar inventory 和 label 独立于 `codespace.managed=true` 的 environment inventory。
- Sidecar 没有 project workspace、environment SSH port、login alias、deploy key、
  repository 或生成的 SSH 投影。
- 创建或删除 environment 不得创建、替换或删除 host sidecar。
- Sidecar 故障可以反映在 host 状态中，但不得破坏 environment inventory。
- 持久服务数据只能使用 sidecar contract 管理的 host storage，不能使用
  `~/codespace/<project>/<instance>`。
- image-prewarm 服务是本 sidecar 契约的**唯一** Podman socket 例外：允许启动器把宿主
  rootful Podman socket bind-mount 进 sidecar 供其调用 Podman REST API，且仅用于按清单
  `pull` 镜像和清理 dangling 镜像。除此之外，镜像与 sidecar 仍不得携带 Podman socket、
  控制面、workspace mount、provider token 或 repository credential。

## 容器契约

镜像固定为 `ghcr.io/curoky/devspace:codespace-sidecar`，host 内 container name 固定为
`codespace-sidecar`。

容器以 s6 作为 PID 1，并按以下参数启动 Atuin server：

- 默认监听 `127.0.0.1`；
- 端口 `8002`；
- 禁止开放注册；
- 创建容器时必须提供 `ATUIN_DB_URI`。

macOS 启动器将容器内监听地址改为 `0.0.0.0`，使 Podman 能从隔离的 bridge network
转发端口，但在 macOS host 上只 publish 到 `127.0.0.1:8002`。

同一容器还有一个独立的 s6 longrun 服务 `supercronic`（`rootfs/etc/s6/s6-rc.d/supercronic`），
只负责监督 supercronic 守护进程并加载 `rootfs/etc/supercronic/crontab`；image-prewarm 只是它
调度的一个 job，不再对应单独的 s6 服务。job 脚本 `rootfs/opt/sidecar/image-prewarm.sh` 接受
`pull` 或 `prune` 子命令，用镜像内已有的 `bash` 和 `curl` 调用 bind-mount 进来的宿主 rootful
Podman socket 的 REST API，每次执行一次即退出：

- `pull`（crontab 默认每 10 分钟 `*/10 * * * *`）：逐个 `POST /images/pull` 预拉一份**写死在
  脚本内**的镜像清单（`image-prewarm.sh` 中的 `PREWARM_IMAGES` 数组，改清单直接改脚本，
  不经启动器或环境变量传入，也不自动推导 project 配置）；清单为空则跳过；
- `prune`（crontab 默认每天 `0 8 * * *`，`CRON_TZ=Asia/Shanghai` 即 UTC+8 08:00）：执行
  `POST /images/prune`（无 filter、非 `all`），只清理 dangling 悬空镜像，绝不删除任何仍被
  tag 或受管容器引用的镜像。

改调度直接改 `crontab`（5 字段、无 user 列，时区由其中的 `CRON_TZ` 决定；`CRON_TZ` 需要
镜像内的 `tzdata`）。supercronic 经 binman（`binman.yaml` 的 `link`）安装到
`/opt/sb/store/supercronic/bin/supercronic`。只预热 host 原生平台。可经环境变量覆盖的
参数：`PODMAN_SOCKET`（默认 `/run/podman/podman.sock`）、`PREWARM_TIMEOUT_SECONDS`
（每次请求超时秒数，默认 900）。日志写入容器内 `/var/log/supercronic.log`。

镜像除 image-prewarm 通过 bind mount 使用的宿主 Podman socket（见「不变量」中的唯一例外）
外，不得包含 Python 控制面、内建 Podman socket、project workspace、SSH 服务、provider
token 或 repository credential。Atuin 使用外部数据库，容器不挂载持久服务数据。

在仓库根目录手动构建和运行：

```bash
images/sidecar/build.sh
ATUIN_DB_URI=postgres://... images/sidecar/run-linux.sh
ATUIN_DB_URI=postgres://... images/sidecar/run-macos.sh
```

两个启动器都会替换固定名称的 container 并配置 Podman restart policy，且都把宿主
`/run/podman/podman.sock` bind-mount 进 sidecar 并注入 `PODMAN_SOCKET`（镜像清单与调度
都写死在镜像内，不经启动器传入）。`run-linux.sh` 使用 host network；`run-macos.sh`
将 bridge network 端口 publish 到 macOS loopback。开发镜像中的 Atuin client 始终访问
`http://127.0.0.1:8002`。

## 目录

| 路径 | 职责 |
| --- | --- |
| `Dockerfile` | 组装最小 Debian、standalone Atuin、s6、supercronic 和 rootfs |
| `binman.yaml` | Atuin、supercronic 与 s6 的 standalone package 集合 |
| `rootfs/` | Sidecar 专用 s6 bundle、Atuin 与 supercronic 服务 |
| `rootfs/etc/s6/s6-rc.d/supercronic` | 监督 supercronic 守护进程的 s6 longrun |
| `rootfs/opt/sidecar/image-prewarm.sh` | supercronic 调度的 `pull`/`prune` 子命令脚本 |
| `rootfs/etc/supercronic/crontab` | supercronic 调度：每 10 分钟 pull、每天 08:00 Asia/Shanghai prune |
| `build.sh` | 从仓库根目录构建本地镜像 |
| `run-linux.sh` | 替换 Linux host-network 单例，挂载 Podman socket 并注入 prewarm 配置 |
| `run-macos.sh` | 替换 macOS bridge-network 单例并限制 loopback publish，挂载 Podman socket 并注入 prewarm 配置 |

不得把已删除的 agent service、Python 应用、uv 环境或 workspace mount 复制回镜像；除
image-prewarm 的宿主 Podman socket 例外外，不得把 Podman socket 复制回镜像。

## 控制面边界

镜像和手动启动器已经存在，但本地 Codespace 控制面尚未 reconcile sidecar。实现该生命周期
时必须：

1. 定义 sidecar 专用 label 和严格 inventory 校验。
2. 复用现有 host Podman transport，不增加协议。
3. 幂等确保每个在线已配置 host 存在固定 sidecar。
4. 明确报告缺失、停止、重复或格式错误的 sidecar。
5. 增加生命周期以及在线、离线 host 混合测试。
6. 用最终 label 和 API 同步更新本文、根 [`AGENTS.md`](../../AGENTS.md) 与
   [`controller/AGENTS.md`](../../controller/AGENTS.md)。

除非明确要求，不增加迁移或兼容行为。
