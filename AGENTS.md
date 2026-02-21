# Devspace 架构约束

本文是仓库整体架构、目录职责、仓库级常用操作与跨组件契约的事实来源。子组件契约见
[`controller/AGENTS.md`](controller/AGENTS.md)、[`images/dev/AGENTS.md`](images/dev/AGENTS.md)、
[`images/sidecar/AGENTS.md`](images/sidecar/AGENTS.md)、[`images/wsl/AGENTS.md`](images/wsl/AGENTS.md)。
修改本文覆盖的内容或某子组件契约时，必须在同一变更中同步更新对应 `AGENTS.md`。

## 目标

- 在容器和 macOS 主机上提供可复现的个人开发环境，在一个仓库内管理用户配置、开发镜像与主机初始化。
- 配置脚本声明式、幂等，可安全重复执行。

## 目录职责

| 路径 | 职责 |
| --- | --- |
| `dotfiles/` | 用户级配置及统一入口 `setup.sh` |
| `controller/` | 本地单进程控制面：配置、Podman transport、生命周期、API、Web UI、维护 CLI 和测试 |
| `images/` | 开发镜像（`dev/`）、host 级共享服务镜像（`sidecar/`）与 WSL 发行版镜像（`wsl/`），各带子目录 `AGENTS.md` |
| `host/` | macOS 主机支持（LaunchAgent、Podman/Colima 启动、Homebrew 与静态包） |
| `tools/` | CI、hook 和仓库维护脚本 |
| `.github/workflows/` | 测试、镜像构建、发布和 registry 清理 |
| `.devcontainer/` | 消费已发布开发镜像的 devcontainer 入口 |
| `pyproject.toml`、`uv.lock` | Codespace Python 运行时、依赖和开发工具 |
| `Taskfile.yaml` | 仓库级 `task` 入口，收纳启动、验证、清理和构建常用命令 |
| `lefthook.yml` | pre-commit 与 commit-msg hook |
| `config.yaml` | 控制面配置示例 |
| `deprecated/` | 已废弃、不再维护的历史内容，仅供归档参考 |

## 组件设计

- **Dotfiles**：`dotfiles/` 是跨场景用户配置来源，仅供开发镜像运行时使用的文件放 `images/dev/rootfs/`。
  `setup.sh` 按 `SCENE`（`docker`、`host-linux`，Darwin 分支配桌面编辑器与 LaunchAgent）分发配置：
  `link_path` 为可编辑配置建软链，`copy_path` 以 `0600` 复制需独立权限的配置；`CONF_PATH` 默认
  `$HOME/devspace/dotfiles`，可由第二个参数覆盖。`dotfiles/archive/` 只存未启用历史配置，不被 `setup.sh` 加载。
- **镜像**：`images/dev/` 构建 Codespace 基础与参考开发镜像，`images/sidecar/` 构建 host 级共享服务镜像，
  `images/wsl/` 以 dev 镜像为 `FROM` 二次处理出 WSL2 rootfs。契约见各子目录 `AGENTS.md`。
- **控制面**：`controller/` 是完整本地单进程控制面（配置、Podman transport、生命周期、Git provider、
  SSH 投影、FastAPI、原生 Web UI 和测试），入口 `uv run python -m controller`。它通过 system OpenSSH
  转发远端 rootful Podman socket，或直连已运行的 rootful Podman Machine，不部署远端 HTTP agent。

### CI 与发布

- `ci-codespace.yaml`：Codespace 格式、lint、类型和测试检查。
- `build-codespace-image.yaml`：原生 amd64/arm64 runner 构建并合并多架构开发镜像。
- `build-codespace-sidecar.yaml`：发布 `ghcr.io/curoky/devspace:codespace-sidecar`。
- `build-codespace-wsl.yaml`：以 dev 镜像为 base 二次处理，单 job 构建推送多架构 `codespace-wsl`，
  再按 arch 导出 `devspace-<arch>.wsl` artifact。
- `delete-untagged-images.yaml`：清理 GHCR 无 tag 镜像。

## 常用操作

根目录 `Taskfile.yaml` 用 `task` 收纳下列命令（`task --list` 查看全部）；清理类 task 追加
`-- --no-dry-run` 才执行写操作。下列原始命令同样有效。

```bash
# 配置 dotfiles（可重复执行）
dotfiles/setup.sh docker "$PWD/dotfiles"
dotfiles/setup.sh host-linux "$PWD/dotfiles"

# 启动控制面（完整命令见 controller/AGENTS.md）
uv sync
uv run python -m controller

# 本地构建镜像（不发布，发布由 .github/workflows/ 管理）
images/dev/build.sh
images/sidecar/build.sh
```

## 跨组件契约

以下约束被多个组件依赖，修改时必须同步更新所有调用方和本文：

1. **容器用户**：开发用户固定为 `x`，uid/gid `5230:5230`。
2. **仓库路径**：镜像内仓库路径 `/opt/devspace`，`~/devspace` 指向该目录。
3. **镜像命名**：基础镜像 `ghcr.io/curoky/devspace:base-<distro><version>`，其他镜像
   `ghcr.io/curoky/devspace:<name>`；缓存在 `ghcr.io/curoky/devspace-cache:*`。
4. **服务管理**：开发容器以自建 s6 init 启动。新增服务放入 `images/dev/rootfs/etc/s6/s6-rc.d/` 并加入
   bundle；execline 脚本用 `s6-envdir -Lf -- /run/s6/container_environment` 读容器环境，该目录仅 root 和
   `x` 可读。`workspace-init` 必须先于 `sshd` 和 `home-init` 完成，把 `/workspace` 归属到 `5230:5230`。
5. **网络边界**：环境 sshd 只绑定宿主 loopback；访问必须经配置的 SSH host route。
6. **共享服务**：每个 host 只有一个固定名称的 `codespace-sidecar`，不附属于 project/instance。Atuin 仅经
   宿主 `127.0.0.1:8002` 暴露。sidecar 的 image-prewarm 定时任务是唯一允许 bind-mount 宿主 rootful
   Podman socket 的共享服务，仅按脚本内写死清单预拉镜像与清理 dangling 镜像。
7. **平台选择**：project 每个 `host` 条目 `platform` 只能省略或设为 `linux/amd64`、`linux/arm64`；
   省略时库存 label 用 `native`。
8. **文档语言**：说明与约束文档用中文；代码标识、命令、协议名和外部 API 保留原文。

## 变更规则

- 新增工具配置：更新 `dotfiles/<tool>/` 和 `dotfiles/setup.sh`。
- 修改 Codespace 配置、生命周期、API、host contract：同步更新 [`controller/AGENTS.md`](controller/AGENTS.md)；
  涉及开发镜像更新 [`images/dev/AGENTS.md`](images/dev/AGENTS.md)，涉及 sidecar 更新
  [`images/sidecar/AGENTS.md`](images/sidecar/AGENTS.md)；影响跨组件契约时同步本文。
- 不修改与任务无关的 s6、Atuin client、Ollama、home-init、sshd。
- Host 共享服务资产只放 `images/sidecar/`，不进 project 生命周期模块；sidecar inventory 与 environment
  inventory 必须分离。除 sidecar image-prewarm 的宿主 Podman socket 例外外，不得恢复 Podman socket、
  Python HTTP agent 或 workspace mount。
- 本地控制面的 Python、静态资源、启动器和测试全保留在 `controller/`。
- 优先添加针对受影响模块的聚焦测试；不恢复已删除的兼容目录、远端 Python agent 或 Node Web 构建链。

## 相关文档

- [`controller/AGENTS.md`](controller/AGENTS.md)、[`images/dev/AGENTS.md`](images/dev/AGENTS.md)、
  [`images/dev/dev-environment.md`](images/dev/dev-environment.md)、[`images/sidecar/AGENTS.md`](images/sidecar/AGENTS.md)、
  [`images/wsl/AGENTS.md`](images/wsl/AGENTS.md)。
- `docs/codespace-image-ghcr-timeout-investigation.md`：多架构镜像访问 GHCR 超时调查记录。

## 已知边界

- `dotfiles/setup.sh` 的 `CONF_PATH` 默认值仍待移除，变更前需核对所有调用方。
- workflow 中被注释的 matrix 项表示暂停构建，不代表源码已废弃。
