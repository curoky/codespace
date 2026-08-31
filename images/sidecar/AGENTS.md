# Codespace Sidecar 约束

本目录保存 Codespace host 级共享服务的容器资产。每个已配置 host 只有一个 sidecar container，
服务该 host 上全部开发环境，不属于任何 workspace/instance。当前共享服务是 Atuin server 和 image-prewarm 定时任务。

## 不变量

- 每个 host 最多一个 sidecar，identity 只由 host 决定，不含 workspace/instance ID。
- 共享服务只经 host loopback 暴露：Linux 用 host network；macOS Podman Machine 用 bridge network 并仅向
  loopback publish 端口。
- Sidecar inventory 和 label 独立于 `codespace.managed=true` 的 environment inventory。
- Sidecar 没有 workspace mount、environment SSH port、login alias、deploy key、repository 或 SSH 投影。
- 创建或删除 environment 不得创建、替换或删除 host sidecar；sidecar 故障可反映在 host 状态，但不得破坏
  environment inventory。
- 持久服务数据只用 sidecar contract 管理的 host storage，不用
  `~/codespace/workspaces/<workspace>/<instance>`。
- image-prewarm 是本契约**唯一** Podman socket 例外：允许启动器把宿主 rootful Podman socket bind-mount 进
  sidecar 供调用 Podman REST API，且仅用于按清单 `pull` 镜像和清理 dangling 镜像。除此外，镜像与 sidecar
  仍不得携带 Podman socket、控制面、workspace mount、provider token 或 repository credential。

## 容器契约

镜像固定 `ghcr.io/curoky/devspace:codespace-sidecar`，host 内 container name 固定 `codespace-sidecar`。

容器以 s6 为 PID 1，启动 Atuin server：默认监听 `127.0.0.1`，端口由 `ATUIN_PORT` 配置（默认 `8002`），
禁开放注册、创建时必须提供
`ATUIN_DB_URI`（启动器不再写死连接串，改由宿主 Podman secret `atuin_db_uri` 以 `type=env,target=ATUIN_DB_URI`
注入；secret 缺失时启动器 fail-fast）。macOS 启动器把容器内监听改为 `0.0.0.0` 以便 Podman 从 bridge network
转发端口，并把同一个 `ATUIN_PORT` publish 到 host loopback。

独立 s6 longrun `supercronic`（`rootfs/etc/s6/s6-rc.d/supercronic`）加载 `rootfs/etc/supercronic/crontab`
调度 image-prewarm job；脚本 `rootfs/opt/sidecar/image-prewarm.sh` 的 `pull`/`prune` 子命令用镜像内
`bash`/`curl` 调宿主 rootful Podman socket REST API。关键约束:

- 预热清单**写死在脚本内**（`PREWARM_IMAGES`），不经启动器/环境变量传入，也不推导 workspace 配置。
- `prune` 只清 dangling 镜像（`POST /images/prune` 无 filter、非 `all`），绝不删除仍被 tag 或受管容器引用的镜像。
- 只预热 host 原生平台。

改调度改 `crontab`（`CRON_TZ` 决定时区，需镜像内 `tzdata`）。可用环境变量 `PODMAN_SOCKET`
（默认 `/run/podman/podman.sock`）、`PREWARM_TIMEOUT_SECONDS`（默认 900）覆盖。

除 image-prewarm 经 bind mount 使用的宿主 Podman socket 外（见「不变量」），镜像不得包含 Python 控制面、
内建 Podman socket、workspace mount、SSH 服务、provider token 或 repository credential。Atuin 用外部数据库，
容器不挂载持久服务数据。

在仓库根构建镜像；`run-*.sh` 仅用于镜像本地 smoke test（先注册宿主 Podman secret）：

```bash
images/sidecar/build.sh
printf '%s' "$ATUIN_DB_URI" | podman secret create atuin_db_uri -
images/sidecar/run-linux.sh
images/sidecar/run-macos.sh
```

两个启动器都替换固定名称 container、配置 Podman restart policy，并 bind-mount 宿主
`/run/podman/podman.sock` 并注入 `PODMAN_SOCKET`；连接串以 Podman secret `atuin_db_uri` 注入，缺失即退出。
`run-linux.sh` 用 host network；`run-macos.sh` 把 bridge network 的固定端口 `8002` publish 到 macOS
loopback。两个 smoke-test 启动器不接受端口配置，开发镜像中的 Atuin client 固定访问
`http://127.0.0.1:8002`。

## 目录

| 路径 | 职责 |
| --- | --- |
| `Dockerfile` | 组装最小 Debian、standalone Atuin、s6、supercronic 和 rootfs |
| `binman.yaml` | Atuin、supercronic 与 s6 的 standalone package 集合 |
| `rootfs/` | Sidecar 专用 s6 bundle、Atuin 与 supercronic 服务 |
| `rootfs/etc/s6/s6-rc.d/supercronic` | 监督 supercronic 守护进程的 s6 longrun |
| `rootfs/opt/sidecar/image-prewarm.sh` | supercronic 调度的 `pull`/`prune` 子命令脚本 |
| `rootfs/etc/supercronic/crontab` | image-prewarm 调度表 |
| `build.sh` | 从仓库根构建本地镜像 |
| `run-linux.sh` | 替换 Linux host-network 单例，使用固定端口 `8002` 并挂载 Podman socket |
| `run-macos.sh` | 替换 macOS bridge-network 单例，向 loopback publish 固定端口 `8002` 并挂载 Podman socket |

## 控制面边界

Sidecar 现由控制面作为 host 级 **deployment** 原生管理（配置项 `deployments.sidecar`，见
[`controller/DESIGN.md`](../../controller/DESIGN.md#deployment-reconcile)）：容器名 `codespace-sidecar`、只带
`codespace.deployment*` label、经 `hosts.<host>.deployments` 选择落到哪些 host，UI 上点 Deploy/Clean 即完成
reconcile 与清理。Atuin 用外部数据库、无持久服务数据，故 deployment 通常无需 `${DEPLOYMENT_DATA}` volume；
`atuin_db_uri` 仍以 `env` 注入且须先经 `sync_secrets` 注册，缺失即 fail-fast。服务端口由
`deployments.sidecar.container.environment` 中的 `ATUIN_PORT` 配置，默认 `8002`；bridge network 下必须让
`published_ports` 的容器端口与它一致。

`run-linux.sh` 与 `run-macos.sh` 只验证镜像运行契约，不是另一套生产生命周期，不得引入独立配置。

修改 sidecar 部署形态（label、inventory、容器块、注入 secret）时，必须用最终 label 和 API 同步更新本文、根
[`AGENTS.md`](../../AGENTS.md)、[`controller/AGENTS.md`](../../controller/AGENTS.md) 与
[`controller/DESIGN.md`](../../controller/DESIGN.md)。
