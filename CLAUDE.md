# Devspace 架构约束

本文是仓库架构、目录职责、常用操作和跨组件契约的事实来源。修改这些内容时，必须在
同一变更中更新本文。

## 目标

- 在容器和 macOS 主机上提供可复现的个人开发环境。
- 在一个仓库内管理用户配置、开发镜像、工具链构建和主机初始化。
- 配置脚本保持声明式、幂等，可安全重复执行。
- CUDA、GCC、LLVM、Python、TensorFlow 等重型工具链独立构建，再由下游镜像消费。

## 目录职责

| 路径 | 职责 |
| --- | --- |
| `dotfiles/` | 用户级配置及统一入口 `setup.sh` |
| `codespace/` | 本地控制面、开发镜像、共享服务和 macOS 主机支持 |
| `images/` | GCC、PyTorch、TensorFlow、ISO 等派生镜像 |
| `deps/` | CUDA、GCC、LLVM、Python、TensorFlow 等独立构建器 |
| `tools/` | CI、hook 和仓库维护脚本 |
| `.github/workflows/` | 测试、镜像构建、发布和 registry 清理 |
| `.devcontainer/` | 消费已发布开发镜像的 devcontainer 入口 |
| `pyproject.toml`、`uv.lock` | Codespace Python 运行时、依赖和开发工具 |
| `lefthook.yml` | pre-commit 与 commit-msg hook |

## 组件设计

### Dotfiles

`dotfiles/` 是跨场景用户配置的来源。仅供开发镜像运行时使用的文件放在
`codespace/images/dev/rootfs/`。`dotfiles/setup.sh` 按运行场景分发配置：

- `link_path` 为可编辑配置创建符号链接。
- `copy_path` 以 `0600` 权限复制需要独立权限控制的配置。
- `SCENE` 支持 `docker` 和 `host-linux`；Darwin 分支配置桌面编辑器与 LaunchAgent。
- `CONF_PATH` 默认是 `$HOME/devspace/dotfiles`，也可由第二个参数显式传入。

`dotfiles/archive/` 只保存未启用的历史配置，不得假定其中内容会被 `setup.sh` 加载。

### 镜像

镜像分为三层：

1. `codespace/images/dev/` 构建 Codespace 基础与参考开发镜像。它组合 `/opt/sb` 静态工具、
   Nix、Rust、Java、Node.js、Go、uv、Conda、dotfiles 和自建 s6 init。
2. `images/` 在基础镜像之上构建 GCC、PyTorch、TensorFlow 和 ISO 等用途镜像。
3. `deps/` 独立构建上游工具链，产物供派生镜像或外部流程消费。

开发镜像不使用 s6-overlay。`codespace/images/dev/script/setup-s6.sh` 从 `/opt/sb/store`
中的 s6/execline 二进制生成 `/etc/s6/init` 和 `/etc/s6/db`。
Container 专用 SSH config 位于 `codespace/images/dev/rootfs/home/x/.ssh/config`，
为所有目标启用 GSSAPI 认证与凭据委派；不得复用带 host 凭据代理的
`dotfiles/ssh/user.ssh_config`。GitHub/GitLab host key 固定在同目录的 `known_hosts`，
provider 连接必须使用严格校验。

### Codespace

`codespace/client/` 是完整的本地单进程控制面，包括配置、Podman transport、生命周期、
Git provider、SSH 投影、FastAPI、原生 Web UI 和测试。入口是：

```bash
uv run python -m codespace.client
```

它通过 system OpenSSH 转发远端 rootful Podman Unix socket，或直接连接已运行的 rootful
Podman Machine；不部署远端 HTTP agent。完整契约见
[`codespace/CLAUDE.md`](codespace/CLAUDE.md)。
固定登录 key、SSH 公共配置和 image host key 位于 `codespace/client/assets/ssh/`，启动时
原子安装到 `~/.ssh/codespace/`；动态 host 文件只保存端口与代理路由。

### CI 与发布

- `ci-codespace.yaml` 运行 Codespace 格式、lint、类型和测试检查。
- `build-codespace-image.yaml` 在原生 amd64/arm64 runner 上构建并合并多架构开发镜像。
- `build-codespace-sidecar.yaml` 发布 `ghcr.io/curoky/devspace:codespace-sidecar`。
- `build-image.yaml` 与 `build-iso.yaml` 构建派生镜像和 ISO。
- `deps-*.yaml` 独立重建工具链。
- `delete-untagged-images.yaml` 清理 GHCR 中无 tag 的镜像。

## 常用操作

### 配置 Dotfiles

`dotfiles/setup.sh` 接收运行场景和配置目录，可重复执行：

```bash
dotfiles/setup.sh docker "$PWD/dotfiles"
dotfiles/setup.sh host-linux "$PWD/dotfiles"
```

### 启动 Codespace

先按 [`codespace/CLAUDE.md`](codespace/CLAUDE.md#配置) 创建
`~/.config/codespace/config.yaml`，再启动控制面：

```bash
uv sync
uv run python -m codespace.client
```

服务只监听 `127.0.0.1:8003`。后台运行使用：

```bash
codespace/client/run.sh
```

### 验证 Codespace

```bash
uv run ruff format --check codespace/client
uv run ruff check codespace/client
uv run mypy codespace/client
uv run pytest codespace/client/tests
uv lock --check
```

### 构建镜像

```bash
codespace/images/dev/build.sh
codespace/images/sidecar/build.sh
task --dir deps/gcc all
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
   `codespace/images/dev/rootfs/etc/s6/s6-rc.d/` 并加入相应 bundle；execline 脚本通过
   `s6-envdir -Lf -- /run/s6/container_environment` 读取容器环境，该目录仅允许 root 和
   `x` 读取。`workspace-init` 必须先于 `sshd` 和 `home-init` 完成，把挂载的 `/workspace`
   归属到 `5230:5230`。
5. **网络边界**：环境 sshd 只绑定宿主 loopback；访问必须经过配置的 SSH host route。
6. **共享服务**：每个 Codespace host 只有一个固定名称的 `codespace-sidecar`，不得附属于
   project 或 instance。Atuin 仅通过宿主 `127.0.0.1:8002` 暴露。
7. **平台选择**：project 的每个 `host` 条目 `platform` 只能省略或设为 `linux/amd64`、
   `linux/arm64`；省略时库存 label 使用 `native`。
8. **文档语言**：仓库说明与约束文档使用中文；代码标识、命令、协议名和外部 API 保留原文。

## 变更规则

- 新增工具配置：更新 `dotfiles/<tool>/` 和 `dotfiles/setup.sh`。
- 新增派生镜像：创建 `images/<name>/`，并接入对应 workflow matrix。
- 新增依赖构建器：创建 `deps/<name>/`，并增加 `deps-<name>.yaml`。
- 修改 Codespace 配置、生命周期、API、host contract 或 sidecar：同步更新
  `codespace/CLAUDE.md`；涉及 sidecar 时还要更新
  `codespace/images/sidecar/CLAUDE.md`。
- 不恢复已删除的兼容目录、远端 Python agent 或 Node Web 构建链。

## 相关文档

- `codespace/CLAUDE.md`：Codespace 配置、生命周期、API 与 host contract。
- `codespace/images/dev/dev-environment.md`：开发镜像内的工具路径与使用方式。
- `codespace/images/sidecar/CLAUDE.md`：Host 级共享服务约束。
- `docs/codespace-image-ghcr-timeout-investigation.md`：多架构镜像访问 GHCR 超时的调查记录。

## 已知边界

- `dotfiles/setup.sh` 的 `CONF_PATH` 默认值仍标记为待移除，变更前需核对所有调用方。
- workflow 中被注释的 matrix 项表示暂停构建，不代表对应源码已废弃。
