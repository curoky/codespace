# WSL 镜像约束

`images/wsl/` 把开发镜像（`images/dev/`）二次处理成可导入 WSL2 的发行版 rootfs。它以
`ghcr.io/curoky/devspace:codespace-ubuntu26.04`（Ubuntu 版 dev 镜像）为 `FROM`，只叠加 WSL
专属资产并重编译 s6-rc 数据库，不修改 `images/dev/` 的任何文件。选 Ubuntu base 是因为 WSL2
用户预期的发行版是 Ubuntu；dev 镜像本身 base 参数化（`ARG BASE_IMAGE`），CI 已在产出
`codespace-ubuntu26.04`，故直接复用、无需改 `images/dev/`。

本文是 WSL 镜像结构、init 机制、SSH 可达性与 Windows 侧保活契约的事实来源。仓库整体架构见
仓库根 [`AGENTS.md`](../../AGENTS.md)；被复用的开发镜像契约见
[`images/dev/AGENTS.md`](../dev/AGENTS.md)。修改 WSL 镜像契约时，必须在同一变更中同步更新本文。

## 与容器模型的三个根本差异

导出 WSL rootfs 用 `docker export`（压平单层文件系统），**不是** `docker save`（保留分层与
镜像 config）。由此产生三条硬约束，决定了本目录的全部设计：

1. **镜像 config 全部丢失**：`export` 丢弃 `ENTRYPOINT`/`CMD`/`ENV`，WSL 也不读 OCI config。
   dev 镜像 `ENV` 注入的 nix/rust/conda/s6 PATH 因此在导出的 rootfs 里消失，但**无需在本目录补偿**：
   dev 的 [`/etc/zsh/zshenv`](../dev/rootfs/etc/zsh/zshenv) 已无条件把这些路径加回（见「PATH」）。
   运行时行为只能来自 rootfs 内的 `/etc/wsl.conf` 与 `/opt/wsl/boot.sh`。
2. **PID 1 恒为 WSL 的 `/init`**：dev 镜像的 ENTRYPOINT `s6-linux-init` 只在自己是 PID 1 时工作；
   在 WSL 里它会退化成 `s6-linux-init-telinit` 而失效。因此**不复用** `/etc/s6/init/bin/init`，
   改由 `/opt/wsl/boot.sh` 手动拉起 s6 监督树。
3. **默认用户默认是 root**：`wsl --import` 不执行 OOBE，`/etc/wsl.conf` 的 `[user] default=x`
   是设定默认登录用户的唯一途径（用户 `x`、uid 5230 已存在于导出的 rootfs 中）。

## init 机制

`/etc/wsl.conf` 的 `[boot] command = /opt/wsl/boot.sh` 由 WSL 的 `/init` 以 root 异步执行
（不阻塞登录 shell）。`boot.sh`：

1. `sysctl -p /etc/sysctl.d/custom.conf`（WSL 无 systemd 自动加载 inotify/ptrace 调优）；
2. `mkdir -p /run/s6/container_environment`——各服务 `run` 脚本的 `s6-envdir -Lf` 走默认
   strict 模式，该目录缺失会以 111 退出，故必须存在（空目录即可）；
3. 写 `/run/s6/container_environment/SSHD_BIND=0.0.0.0`，让 sshd 监听所有接口以便 LAN 可达；
4. 前台 `exec s6-svscan /run/service`；就绪后后台执行 `s6-rc-init -c /etc/s6/db /run/service`
   与 `s6-rc -up change wsl`。

s6-svscan 是 WSL `/init` 的子进程（非 PID 1）。skarnet 官方确认 s6-svscan 不必是 PID 1 也能可靠
监督；孤儿由真正的 PID 1（WSL `/init`）回收，不会堆积僵尸。

## `wsl` s6 bundle

新增精简 bundle `rootfs/etc/s6/s6-rc.d/wsl`，`contents.d/` 含 `sshd`、`atuin-login`、
`atuin-daemon`、`supercronic`。sshd 的 `dependencies.d/workspace-init` 由 s6-rc 自动带起（WSL 下
`chown /workspace` 无副作用）。dev 镜像 user bundle 中的 `home-init`、`rclone-webdav`、
`copyparty-webdav` **不进** WSL bundle：

- 不跑 `home-init`：dotfiles 已在 dev 镜像构建期烤进 `/home/x`（[dev Dockerfile](../dev/Dockerfile)
  以 x 与 root 各跑一次 `setup.sh`），运行期那次仅为刷新；WSL 无外部 `/workspace` 挂载，
  跳过 home-init 也就避免了把 `~/.vscode-server` 等软链到不存在的持久化目录。**因此完全不修改
  `images/dev/script/home-init.sh`。** `home-init` 不在 `wsl` bundle 的 `contents.d/`，也无其他
  bundle 成员依赖它（`atuin-login` 曾在 dev 里依赖 `home-init`，该依赖已从 dev 源移除，见下），
  故 s6-rc 不会把它拉进 `wsl` 闭包，无需在本镜像里做任何依赖删除。
- 不跑 webdav：WSL 无 workspace 导出需求。
- 跑 `supercronic`：随 dev 契约保留定时任务服务，当前 crontab 仍空、零 job。

### atuin 在 WSL 的实际行为

`atuin-login`/`atuin-daemon` 已加入 bundle，但 atuin 配置**保留** [`config.toml`](../../dotfiles/atuin/config.toml)
的 `sync_address = "http://127.0.0.1:8002"`（宿主 sidecar）。WSL 不连 sidecar，8002 无人监听：

- [`atuin-login/up`](../dev/rootfs/etc/s6/s6-rc.d/atuin-login/up) 末尾的 `atuin sync` 对 loopback
  的 8002 **立即得到 connection refused**（不挂起，故不阻塞 boot），该 oneshot up 失败；
- `atuin-daemon` 依赖 `atuin-login`，s6-rc 对失败依赖的下游不启动，daemon **实际不常驻**。

净结果：boot 后 `sshd` 与 `supercronic` 正常，atuin 一对服务处于失败/未起状态，直到 8002 出现真实
监听者（如把 WSL 的 8002 转发到某个 atuin server）。这是刻意保留 8002 指向的直接后果；若要让
daemon 在 WSL 本地常驻（仅本地历史/搜索、暂不同步），需另断 `atuin-daemon→atuin-login` 依赖，
本方案未做。

因为新增了 bundle，`Dockerfile` 必须重跑 `s6-rc-compile` 覆盖 dev 镜像里旧的 `/etc/s6/db`，
否则 `s6-rc change wsl` 找不到该 bundle。

## PATH

`docker export` 丢弃镜像 `ENV`，dev 镜像靠 `ENV` 注入的 nix/rust/conda/s6 路径在导出的 rootfs
里全部消失。**本目录不做任何补偿**：dev 的 [`/etc/zsh/zshenv`](../dev/rootfs/etc/zsh/zshenv) 在
重置基础 PATH 后无条件把这些路径加回（`typeset -U` 去重、`[ -d ]` 跳过缺失目录），且用户 `x`
的登录 shell 在 dev 构建期已 `chsh` 成 zsh 并随 rootfs 进 WSL。所以每个 WSL zsh 会话——交互或
`ssh host <cmd>` 之类非交互——都只凭 rootfs 恢复完整 PATH，无需硬编码，也不再往 `zshenv.d`/
`profile.d` 冻结快照。

## SSH 可达性

- `boot.sh` 注入 `SSHD_BIND=0.0.0.0`；sshd 端口默认 22，认证复用 dev 镜像契约：只认 ed25519
  公钥、禁密码与 root 登录，授权公钥为 [`authorized_keys`](../dev/rootfs/home/x/.ssh/authorized_keys)
  中的 `codespace-login`。要让自己的 macOS 连入，需持有对应私钥或在本目录 rootfs 覆盖该公钥。
- WSL2 默认 NAT 网络：LAN 里的 macOS 连不进来，需二选一：
  - **mirrored 网络模式**（Windows 11 22H2+）：`.wslconfig` 设 `networkingMode=mirrored`，
    WSL 共享 Windows 网络，macOS 直接连 Windows 的 LAN IP，免 `netsh portproxy`；
  - **NAT + 端口转发**：Windows 上 `netsh interface portproxy` 把 `Windows_LAN_IP:22` 转发到
    WSL IP，并开放防火墙入站。WSL IP 每次启动可能变，portproxy 需重设。

## Windows 侧保活（macOS 能连接的硬前提）

WSL 实例在无「被跟踪的会话进程」时约 15 秒后被回收；`[boot] command` 拉起的 s6/sshd
**不计入**保活。实例一旦回收，sshd 停止、portproxy 目标 IP 消失，且连接**不会**唤醒实例。因此
保活是「macOS 能连」的硬前提，且**只能在 Windows 侧配置，无法烤进 rootfs**：

- **首选（声明式）** `windows/wslconfig.sample`：`.wslconfig` 设 `[general] instanceIdleTimeout=-1`
  （关掉 15 秒实例回收）+ `[wsl2] vmIdleTimeout=-1`。`instanceIdleTimeout` 是较新 WSL 键，旧版
  静默忽略，需 `wsl --version` 并按文件内步骤实测。
- **兜底** `windows/setup-keepalive.ps1`：注册开机 Scheduled Task 以 SYSTEM 运行
  `wsl -d devspace -u root -- sleep infinity`（经 wsl.exe 会话的进程才计入保活），并关闭任务的执行
  时限（否则 3 天后被杀）。对所有 WSL 版本有效，包括 2.6.x 保活回归版本。

## 目录

| 路径 | 职责 |
| --- | --- |
| `Dockerfile` | `FROM` dev 镜像；叠加 WSL rootfs；重编译 s6-rc db（PATH 由 dev zshenv 恢复，不在此冻结） |
| `build.sh` | 从仓库根构建 `ghcr.io/curoky/devspace:codespace-wsl` |
| `export.sh` | `docker create` + `docker export \| gzip` 产出可导入的 `devspace.wsl` |
| `rootfs/etc/wsl.conf` | 默认用户 `x`、`[boot] command` 指向 boot.sh、interop 调优 |
| `rootfs/opt/wsl/boot.sh` | 替代 s6-linux-init stage1：手动 s6-svscan + s6-rc-init + s6-rc change wsl |
| `rootfs/etc/s6/s6-rc.d/wsl` | 精简 bundle，仅监督 sshd |
| `windows/wslconfig.sample` | 首选保活：`instanceIdleTimeout=-1` 的 `.wslconfig` 片段 |
| `windows/setup-keepalive.ps1` | 兜底保活：开机 Scheduled Task 运行 `sleep infinity` |

## 构建与导出

在仓库根目录：

```bash
images/dev/build.sh ubuntu:26.04   # 先构建 Ubuntu 版 dev 镜像（codespace-ubuntu26.04）
images/wsl/build.sh                # 二次处理出 codespace-wsl
images/wsl/export.sh               # 产出 devspace.wsl
```

Windows 上：`wsl --install --from-file devspace.wsl`（或 `wsl --import devspace <InstallDir>
devspace.wsl`），应用 `windows/wslconfig.sample` 后按其中步骤验证常驻；不生效则运行
`windows/setup-keepalive.ps1`。

## 变更规则

- 不修改 `images/dev/`：WSL 专属改动全部落在 `images/wsl/`。若确需改动 dev 的 s6/sshd/home-init，
  按仓库根与 dev 的 `AGENTS.md` 同步更新。
- 新增/移除 WSL bundle 服务后，必须保持 `Dockerfile` 的 `s6-rc-compile` 重编译步骤。
- 保活与网络属 Windows 侧配置，只能放 `windows/` 并在本文说明，不得试图写进 rootfs。
- 不引入 systemd、s6-overlay 或第二套 init；WSL 复用 dev 镜像既有的 s6-rc 服务定义。
