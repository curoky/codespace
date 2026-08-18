# Devspace 架构约束

本文是仓库整体架构、目录职责、仓库级常用操作与跨组件契约的事实来源。控制面（Codespace）
生命周期、API、配置与 host contract 见 [`controller/AGENTS.md`](controller/AGENTS.md)；开发镜像契约见
[`images/dev/AGENTS.md`](images/dev/AGENTS.md)；host 级共享服务见
[`images/sidecar/AGENTS.md`](images/sidecar/AGENTS.md)。修改本文覆盖的内容时，必须在同一变更中更新本文；
改动某个子组件的契约时，同步更新对应子目录的 `AGENTS.md`。

## 目标

- 在容器和 macOS 主机上提供可复现的个人开发环境。
- 在一个仓库内管理用户配置、开发镜像和主机初始化。
- 配置脚本保持声明式、幂等，可安全重复执行。

## 目录职责

| 路径 | 职责 |
| --- | --- |
| `dotfiles/` | 用户级配置及统一入口 `setup.sh` |
| `controller/` | 本地单进程控制面：配置、Podman transport、生命周期、API、Web UI、维护 CLI 和测试；契约见 [`controller/AGENTS.md`](controller/AGENTS.md) |
| `images/` | 开发镜像（`dev/`）、host 级共享服务镜像（`sidecar/`）与 WSL 发行版镜像（`wsl/`，二次处理 dev 镜像），各带子目录 `AGENTS.md` |
| `host/` | macOS 主机支持（LaunchAgent、Podman/Colima 启动、Homebrew 与静态包） |
| `tools/` | CI、hook 和仓库维护脚本 |
| `.github/workflows/` | 测试、镜像构建、发布和 registry 清理 |
| `.devcontainer/` | 消费已发布开发镜像的 devcontainer 入口 |
| `pyproject.toml`、`uv.lock` | Codespace Python 运行时、依赖和开发工具 |
| `Taskfile.yaml` | 仓库级 `task` 入口，收纳启动、验证、清理和构建常用命令 |
| `lefthook.yml` | pre-commit 与 commit-msg hook |
| `config.yaml` | 控制面配置示例 |
| `deprecated/` | 已废弃、不再维护的历史内容（含旧的 `deps/`、`images/` 及其 workflow），仅供归档参考 |

## 组件设计

### Dotfiles

`dotfiles/` 是跨场景用户配置的来源。仅供开发镜像运行时使用的文件放在
`images/dev/rootfs/`。`dotfiles/setup.sh` 按运行场景分发配置：

- `link_path` 为可编辑配置创建符号链接。
- `copy_path` 以 `0600` 权限复制需要独立权限控制的配置。
- `SCENE` 支持 `docker` 和 `host-linux`；Darwin 分支配置桌面编辑器与 LaunchAgent。
- `CONF_PATH` 默认是 `$HOME/devspace/dotfiles`，也可由第二个参数显式传入。

`dotfiles/archive/` 只保存未启用的历史配置，不得假定其中内容会被 `setup.sh` 加载。

### 镜像

`images/dev/` 构建 Codespace 基础与参考开发镜像，`images/sidecar/` 构建 host 级共享服务镜像，
`images/wsl/` 以 dev 镜像为 `FROM` 二次处理出可导入 WSL2 的发行版 rootfs。
开发镜像结构、s6 init、容器 SSH 契约与镜像 host contract 见
[`images/dev/AGENTS.md`](images/dev/AGENTS.md)；sidecar 约束见
[`images/sidecar/AGENTS.md`](images/sidecar/AGENTS.md)；WSL 镜像约束见
[`images/wsl/AGENTS.md`](images/wsl/AGENTS.md)。

### 控制面

`controller/` 是完整的本地单进程控制面，包括配置、Podman transport、生命周期、
Git provider、SSH 投影、FastAPI、原生 Web UI 和测试。入口是：

```bash
uv run python -m controller
```

它通过 system OpenSSH 转发远端 rootful Podman Unix socket，或直接连接已运行的 rootful
Podman Machine；不部署远端 HTTP agent。完整的控制面范围、配置、连接机制、生命周期、SSH
投影、Web/HTTP API 与安全边界见 [`controller/AGENTS.md`](controller/AGENTS.md)。

### CI 与发布

- `ci-codespace.yaml` 运行 Codespace 格式、lint、类型和测试检查。
- `build-codespace-image.yaml` 在原生 amd64/arm64 runner 上构建并合并多架构开发镜像。
- `build-codespace-sidecar.yaml` 发布 `ghcr.io/curoky/devspace:codespace-sidecar`。
- `build-codespace-wsl.yaml` 以 dev 镜像为 base 二次处理，单 job 一次性构建并推送多架构
  `codespace-wsl` 到 GHCR，再按 arch 导出 `devspace-<arch>.wsl` build artifact。
- `delete-untagged-images.yaml` 清理 GHCR 中无 tag 的镜像。

## 常用操作

根目录 `Taskfile.yaml` 用 `task` 收纳了下列常用命令，可用 `task --list` 查看全部；清理类
task 追加 `-- --no-dry-run` 才会执行写操作，例如 `task cleanup:workspaces -- --no-dry-run`。
下文命令与对应 task 等价，直接运行原始命令同样有效。

### 配置 Dotfiles

`dotfiles/setup.sh` 接收运行场景和配置目录，可重复执行：

```bash
dotfiles/setup.sh docker "$PWD/dotfiles"
dotfiles/setup.sh host-linux "$PWD/dotfiles"
```

### 启动与维护 Codespace

启动控制面、验证与维护 CLI 的完整命令见 [`controller/AGENTS.md`](controller/AGENTS.md) 的
「常用操作」章节。最短路径：

```bash
uv sync
uv run python -m controller
```

### 构建镜像

```bash
images/dev/build.sh
images/sidecar/build.sh
```

本地构建不会发布镜像，发布流程由 `.github/workflows/` 管理。

## 跨组件契约

以下约束同时被多个组件依赖，修改时必须同步更新所有调用方和本文：

1. **容器用户**：开发用户固定为 `x`，uid/gid 为 `5230:5230`。
2. **仓库路径**：镜像内仓库路径为 `/opt/devspace`，`~/devspace` 指向该目录。
3. **镜像命名**：基础镜像使用 `ghcr.io/curoky/devspace:base-<distro><version>`，
   其他镜像使用 `ghcr.io/curoky/devspace:<name>`；缓存位于
   `ghcr.io/curoky/devspace-cache:*`。
4. **服务管理**：开发容器以自建 s6 init 启动。新增服务必须放入
   `images/dev/rootfs/etc/s6/s6-rc.d/` 并加入相应 bundle；execline 脚本通过
   `s6-envdir -Lf -- /run/s6/container_environment` 读取容器环境，该目录仅允许 root 和
   `x` 读取。`workspace-init` 必须先于 `sshd` 和 `home-init` 完成，把挂载的 `/workspace`
   归属到 `5230:5230`。
5. **网络边界**：环境 sshd 只绑定宿主 loopback；访问必须经过配置的 SSH host route。
6. **共享服务**：每个 Codespace host 只有一个固定名称的 `codespace-sidecar`，不得附属于
   project 或 instance。Atuin 仅通过宿主 `127.0.0.1:8002` 暴露。sidecar 内的 image-prewarm
   定时任务是唯一允许 bind-mount 宿主 rootful Podman socket 的共享服务，仅用于按脚本内写死的
   清单预拉镜像和清理 dangling 镜像，见 [`images/sidecar/AGENTS.md`](images/sidecar/AGENTS.md)。
7. **平台选择**：project 的每个 `host` 条目 `platform` 只能省略或设为 `linux/amd64`、
   `linux/arm64`；省略时库存 label 使用 `native`。
8. **文档语言**：仓库说明与约束文档使用中文；代码标识、命令、协议名和外部 API 保留原文。

## 变更规则

- 新增工具配置：更新 `dotfiles/<tool>/` 和 `dotfiles/setup.sh`。
- 修改 Codespace 配置、生命周期、API、host contract：同步更新
  [`controller/AGENTS.md`](controller/AGENTS.md) 相关章节；涉及开发镜像时更新
  [`images/dev/AGENTS.md`](images/dev/AGENTS.md)，涉及 sidecar 时更新
  [`images/sidecar/AGENTS.md`](images/sidecar/AGENTS.md)；影响跨组件契约时同步本文。
- 不修改 `images/dev/` 中与任务无关的 s6、Atuin client、Ollama、home-init 和 sshd。
- Host 共享服务资产只能放在 `images/sidecar/`，不能进入 project 生命周期模块；sidecar
  inventory 与 environment inventory 必须分离，也不得恢复 Python HTTP agent 或 workspace
  mount。除 sidecar image-prewarm 定时任务经 bind mount 使用的宿主 rootful Podman socket
  这一唯一例外外，不得恢复 Podman socket。
- 本地控制面的 Python、静态资源、启动器和测试全部保留在 `controller/`。
- 优先添加针对受影响模块的聚焦测试，不恢复兼容路径。
- 不恢复已删除的兼容目录、远端 Python agent 或 Node Web 构建链。

## 相关文档

- [`controller/AGENTS.md`](controller/AGENTS.md)：本地控制面范围、配置、生命周期、API 与安全边界。
- [`images/dev/AGENTS.md`](images/dev/AGENTS.md)：开发镜像结构、s6 init 与镜像 host contract。
- [`images/dev/dev-environment.md`](images/dev/dev-environment.md)：开发镜像内的工具路径与使用方式。
- [`images/sidecar/AGENTS.md`](images/sidecar/AGENTS.md)：Host 级共享服务约束。
- `docs/codespace-image-ghcr-timeout-investigation.md`：多架构镜像访问 GHCR 超时的调查记录。

## 已知边界

- `dotfiles/setup.sh` 的 `CONF_PATH` 默认值仍标记为待移除，变更前需核对所有调用方。
- workflow 中被注释的 matrix 项表示暂停构建，不代表对应源码已废弃。
