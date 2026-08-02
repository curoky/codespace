# Codespace Sidecar 约束

本目录保存 Codespace host 级共享服务的容器资产。

## 定义

每个已配置 host 只有一个 sidecar container，服务该 host 上的全部开发环境，不属于任何
project 或 instance。当前共享服务是 Atuin server。

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
  `~/codespace2/<project>/<instance>`。

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

镜像不得包含 Python 控制面、Podman socket、project workspace、SSH 服务、provider
token 或 repository credential。Atuin 使用外部数据库，容器不挂载持久服务数据。

在仓库根目录手动构建和运行：

```bash
codespace/images/sidecar/build.sh
ATUIN_DB_URI=postgres://... codespace/images/sidecar/run-linux.sh
ATUIN_DB_URI=postgres://... codespace/images/sidecar/run-macos.sh
```

两个启动器都会替换固定名称的 container 并配置 Podman restart policy。`run-linux.sh`
使用 host network；`run-macos.sh` 将 bridge network 端口 publish 到 macOS loopback。
开发镜像中的 Atuin client 始终访问 `http://127.0.0.1:8002`。

## 目录

| 路径 | 职责 |
| --- | --- |
| `Dockerfile` | 组装最小 Debian、standalone Atuin、s6 和 rootfs |
| `binman.yaml` | Atuin 与 s6 的 standalone package 集合 |
| `rootfs/` | Sidecar 专用 s6 bundle 和共享服务 |
| `build.sh` | 从仓库根目录构建本地镜像 |
| `run-linux.sh` | 替换 Linux host-network 单例 |
| `run-macos.sh` | 替换 macOS bridge-network 单例并限制 loopback publish |

不得把已删除的 agent service、Python 应用、uv 环境、workspace mount 或 Podman socket
复制回镜像。

## 控制面边界

镜像和手动启动器已经存在，但本地 Codespace 控制面尚未 reconcile sidecar。实现该生命周期
时必须：

1. 定义 sidecar 专用 label 和严格 inventory 校验。
2. 复用现有 host Podman transport，不增加协议。
3. 幂等确保每个在线已配置 host 存在固定 sidecar。
4. 明确报告缺失、停止、重复或格式错误的 sidecar。
5. 增加生命周期以及在线、离线 host 混合测试。
6. 用最终 label 和 API 同步更新本文与 `codespace/CLAUDE.md`。

除非明确要求，不增加迁移或兼容行为。
