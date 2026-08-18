# WSL 镜像约束

`images/wsl/` 以 `ghcr.io/curoky/devspace:codespace-ubuntu26.04`（Ubuntu 版 dev 镜像）为
`FROM`，二次处理成可导入 WSL2 的发行版 rootfs：只叠加 WSL 专属资产并重编译 s6-rc 数据库，
不改 `images/dev/` 任何文件。选 Ubuntu 是因为 WSL2 用户预期发行版为 Ubuntu，且 CI 已产出该 tag。

本文是 WSL 镜像结构、init、SSH 可达性与 Windows 保活契约的事实来源。整体架构见仓库根
[`AGENTS.md`](../../AGENTS.md)，被复用的开发镜像契约见 [`images/dev/AGENTS.md`](../dev/AGENTS.md)。
修改本目录契约时必须同步更新本文。

## 与容器模型的三个根本差异

导出用 `docker export`（压平单层），**不是** `docker save`，由此三条硬约束决定全部设计：

1. **镜像 config 全部丢失**：`export` 丢弃 `ENTRYPOINT`/`CMD`/`ENV`，WSL 也不读 OCI config。
   nix/rust/conda/s6 的 PATH 因此消失，但本目录不补偿——见「PATH」。运行时行为只能来自 rootfs 内的
   `/etc/wsl.conf` 与 `/opt/wsl/boot.sh`。
2. **PID 1 恒为 WSL 的** **`/init`**：dev 的 ENTRYPOINT `s6-linux-init` 只在自己是 PID 1 时工作，
   在 WSL 里退化失效。故不复用 `/etc/s6/init/bin/init`，改由 `/opt/wsl/boot.sh` 手动拉起 s6 监督树。
3. **默认用户默认是 root**：`wsl --import` 不执行 OOBE，`/etc/wsl.conf` 的 `[user] default=x`
   是设定默认登录用户的唯一途径（用户 `x`、uid 5230 已存在于 rootfs）。

## init 机制

`/etc/wsl.conf` 的 `[boot] command = /opt/wsl/boot.sh` 由 `/init` 以 root 异步执行（不阻塞登录 shell）。
`boot.sh`：

1. `sysctl -p /etc/sysctl.d/custom.conf`（WSL 无 systemd 自动加载 inotify/ptrace 调优）；
2. `mkdir -p /run/s6/container_environment`（`s6-envdir -Lf` strict 模式要求该目录存在，空目录即可）；
3. 写 `SSHD_BIND=0.0.0.0` 到该目录，让 sshd 监听所有接口；
4. `exec s6-svscan /run/service`，就绪后后台跑 `s6-rc-init -c /etc/s6/db /run/service` 与 `s6-rc -up change wsl`。

s6-svscan 非 PID 1 也能可靠监督，孤儿由 `/init` 回收。

## `wsl` s6 bundle

新增 bundle 后 `Dockerfile` 必须重跑 `s6-rc-compile` 覆盖旧 `/etc/s6/db`，否则 `s6-rc change wsl`
找不到该 bundle。

## SSH 可达性

- 端口默认 22，认证复用 dev 契约：只认 ed25519 公钥、禁密码与 root，授权公钥为
  [`authorized_keys`](../dev/rootfs/home/x/.ssh/authorized_keys) 中的 `codespace-login`。
  macOS 连入需持对应私钥或在本目录 rootfs 覆盖该公钥。
- WSL2 默认 NAT，LAN 里 macOS 连不进来，二选一：
  - **mirrored**（Windows 11 22H2+）：`.wslconfig` 设 `networkingMode=mirrored`，直接连 Windows LAN IP；
  - **NAT + portproxy**：`netsh interface portproxy` 把 `Windows_LAN_IP:22` 转发到 WSL IP 并放行防火墙；
    WSL IP 每次启动可能变，需重设。

## Windows 侧保活（macOS 能连接的硬前提）

WSL 实例无「被跟踪会话进程」时约 15 秒被回收，`[boot] command` 拉起的 s6/sshd 不计入保活；
回收后连接不会唤醒实例。保活只能在 Windows 侧配置，无法烤进 rootfs：

- **首选** `windows/wslconfig.sample`：`.wslconfig` 设 `[general] instanceIdleTimeout=-1` +
  `[wsl2] vmIdleTimeout=-1`；`instanceIdleTimeout` 是较新键，旧版静默忽略，需按文件步骤实测。
- **兜底** `windows/setup-keepalive.ps1`：注册开机 Scheduled Task 以 SYSTEM 跑
  `wsl -d devspace -u root -- sleep infinity`（经 wsl.exe 会话才计入保活），并关闭执行时限。

## 目录

| 路径                            | 职责                                                                |
| ----------------------------- | ----------------------------------------------------------------- |
| `Dockerfile`                  | `FROM` dev 镜像；叠加 WSL rootfs；重编译 s6-rc db                          |
| `build.sh`                    | 构建 `ghcr.io/curoky/devspace:codespace-wsl`                        |
| `export.sh`                   | `docker create` + `docker export \| gzip` 产出 `devspace.wsl`       |
| `rootfs/etc/wsl.conf`         | 默认用户 `x`、`[boot] command` 指向 boot.sh、interop 调优                   |
| `rootfs/opt/wsl/boot.sh`      | 替代 s6-linux-init stage1：s6-svscan + s6-rc-init + s6-rc change wsl |
| `rootfs/etc/s6/s6-rc.d/wsl`   | 精简 bundle                                                         |
| `windows/wslconfig.sample`    | 首选保活：`instanceIdleTimeout=-1` 片段                                  |
| `windows/setup-keepalive.ps1` | 兜底保活：开机 Scheduled Task                                            |

## 构建与导出

仓库根目录：

```bash
images/dev/build.sh ubuntu:26.04   # 先构建 Ubuntu 版 dev 镜像
images/wsl/build.sh                # 二次处理出 codespace-wsl
images/wsl/export.sh               # 产出 devspace.wsl
```

Windows 上 `wsl --install --from-file devspace.wsl`（或 `wsl --import devspace <InstallDir> devspace.wsl`），
应用 `windows/wslconfig.sample` 后验证常驻，不生效则跑 `windows/setup-keepalive.ps1`。

CI 由 `.github/workflows/build-codespace-wsl.yaml` 单 job（QEMU 多架构）构建并推送多架构
`codespace-wsl` 到 GHCR，再按 arch `docker export | gzip` 产出 `devspace-<arch>.wsl` artifact
（`export` 只 dump 文件系统，异架构无需 QEMU 执行）。OCI 镜像仅供缓存追溯，**不能被 WSL 直接导入**，
终端用户消费 `.wsl` artifact。触发：`images/wsl/**` 或该 workflow 变更、每周定时。base 镜像依赖
`build-codespace-image.yaml` 已发布的 `codespace-ubuntu26.04`。

## 变更规则

- 不修改 `images/dev/`：WSL 专属改动全落在 `images/wsl/`；确需改 dev 的 s6/sshd/home-init 时按仓库根与
  dev 的 `AGENTS.md` 同步更新。
- 增减 WSL bundle 服务后，必须保持 `Dockerfile` 的 `s6-rc-compile` 重编译步骤。
- 保活与网络属 Windows 侧配置，只能放 `windows/`，不得写进 rootfs。
- 不引入 systemd、s6-overlay 或第二套 init。

