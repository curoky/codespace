# Devspace 架构约束

本文是仓库整体架构、目录职责、仓库级常用操作与跨组件契约的事实来源。子组件契约见
[`controller/AGENTS.md`](controller/AGENTS.md)、[`images/dev/AGENTS.md`](images/dev/AGENTS.md)、
[`images/sidecar/AGENTS.md`](images/sidecar/AGENTS.md)、[`images/wsl/AGENTS.md`](images/wsl/AGENTS.md)、
[`images/llm/AGENTS.md`](images/llm/AGENTS.md)。
修改本文覆盖的内容或某子组件契约时，必须在同一变更中同步更新对应 `AGENTS.md`。

## 目标

- 在容器和 macOS 主机上提供可复现的个人开发环境，在一个仓库内管理用户配置、开发镜像与主机初始化。
- 配置脚本声明式、幂等，可安全重复执行。

## 目录职责

| 路径 | 职责 |
| --- | --- |
| `dotfiles/` | 非容器场景专属配置（macOS 桌面/host）与 host 入口 `setup.sh`；跨场景 home 配置见 `images/dev/rootfs/home/x/` |
| `controller/` | 本地单进程控制面：配置、Podman transport、生命周期、API、Web UI、维护 CLI 和测试 |
| `images/` | 开发镜像（`dev/`）、host 级共享服务镜像（`sidecar/`）、WSL 发行版镜像（`wsl/`）与 host 级 LLM serving 镜像（`llm/`），各带子目录 `AGENTS.md` |
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

- **Dotfiles**：跨场景 home 配置的事实来源是 `images/dev/rootfs/home/x/`——这些文件经 `COPY rootfs/ /`
  直接烤入开发镜像的 `$HOME`，无需构建期 `setup.sh`。`dotfiles/` 只保留非容器场景专属配置（macOS 桌面
  编辑器、LaunchAgent、warp/snipaste/mpv，以及 host 专属的 zsh `prune.zshrc`、git `.gitconfig` 等）与容器运行期
  才能落位的模板（trae `sandbox.json`/`traecli.toml`、
  vscode remote-server settings，它们所在目录会被 `home-init` 在 boot 时重链到 `/cache`，烤入会被清掉）。
  `setup.sh` 主要服务 macOS host，按 scene（首参数 `docker`/`host-linux`/`darwin`，缺省按 OS 推断）分发：
  跨场景 home 配置从 `rootfs/home/x` 建软链（单一来源），场景专属配置从 `dotfiles/` 取；`docker` scene 只在
  运行期补写被重链目录内的模板。`link_path` 建软链，`copy_path` 以 `0600` 复制需独立权限的配置；`CONF_PATH`
  默认 `$HOME/devspace/dotfiles`，可由第二参数覆盖。`dotfiles/archive/` 只存未启用历史配置，不被加载。
- **镜像**：`images/dev/` 构建 Codespace 基础与参考开发镜像，`images/sidecar/` 构建 host 级共享服务镜像，
  `images/llm/` 构建 host 级 LLM serving 镜像，`images/wsl/` 以 dev 镜像为 `FROM` 二次处理出 WSL2 rootfs。契约见各子目录 `AGENTS.md`。
- **控制面**：`controller/` 是完整本地单进程控制面（配置、Podman transport、生命周期、Git provider、
  SSH 投影、FastAPI、原生 Web UI 和测试），入口 `uv run python -m controller`。它通过 system OpenSSH
  转发远端 rootful Podman socket，或直连已运行的 rootful Podman Machine，不部署远端 HTTP agent。除逐 project
  的开发 environment 外，它还原生管理 host 级 **deployment**（sidecar、LLM serving 等自包含镜像）：这类容器无
  workspace/SSH 投影/git checkout，由 `hosts.<host>.deployments` 选择部署到哪些 host，UI 上同样点 Deploy/Clean。

### CI 与发布

- `ci-codespace.yaml`：Codespace 格式、lint、类型和测试检查。
- `build-codespace-image.yaml`：原生 amd64/arm64 runner 构建并合并多架构开发镜像。
- `build-codespace-sidecar.yaml`：发布 `ghcr.io/curoky/devspace:codespace-sidecar`。
- `build-codespace-llm.yaml`：matrix 构建推送仅 amd64 的 `llm-vllm`、`llm-sglang` LLM serving 镜像。
- `build-codespace-wsl.yaml`：以 dev 镜像为 base 二次处理，单 job 构建推送多架构 `codespace-wsl`，
  再按 arch 导出 `devspace-<arch>.wsl` artifact。
- `delete-untagged-images.yaml`：清理 GHCR 无 tag 镜像。

## 常用操作

根目录 `Taskfile.yaml` 用 `task` 收纳下列命令（`task --list` 查看全部）；清理类 task 追加
`-- --no-dry-run` 才执行写操作。下列原始命令同样有效。

```bash
# 配置 dotfiles（可重复执行；scene 缺省按 OS 推断）
dotfiles/setup.sh docker "$PWD/dotfiles"       # 容器运行期：仅补写被重链目录内模板
dotfiles/setup.sh host-linux "$PWD/dotfiles"   # 裸 Linux host：链入全部 home 配置
dotfiles/setup.sh darwin "$PWD/dotfiles"       # macOS host（无参数时的默认）

# 启动控制面（完整命令见 controller/AGENTS.md）
uv sync
uv run python -m controller

# 本地构建镜像（不发布，发布由 .github/workflows/ 管理）
images/dev/build.sh
images/sidecar/build.sh

# 在目标 Git 仓库根目录生成 SSH key，并配置当前仓库使用该 key
$HOME/devspace/tools/setup-git-deploy-key.sh
```

## 跨组件契约

以下约束被多个组件依赖，修改时必须同步更新所有调用方和本文：

1. **容器用户**：开发用户固定为 `x`，uid/gid `5230:5230`。
2. **仓库路径**：镜像内仓库路径 `/opt/devspace`，`~/devspace` 指向该目录。
3. **镜像命名**：基础镜像 `ghcr.io/curoky/devspace:base-<distro><version>`，其他镜像
   `ghcr.io/curoky/devspace:<name>`；缓存在 `ghcr.io/curoky/devspace-cache:*`。
4. **服务管理**：开发容器以自建 s6 init 启动。新增服务放入 `images/dev/rootfs/etc/s6/s6-rc.d/` 并加入
   bundle；execline 脚本用 `s6-envdir -Lf -- /run/s6/container_environment` 读容器环境，该目录仅 root 和
   `x` 可读。`workspace-init` 必须先于 `workspace-crypt` 完成，把 `/workspace`、密文根 `/workspace.enc`、
   `/upload` 与 `/cache` 都归属到 `5230:5230`；`workspace-crypt` 再先于 `sshd`、`home-init` 与 WebDAV 服务完成。
5. **网络边界**：环境 sshd 只绑定宿主 loopback；访问必须经配置的 SSH host route。
6. **共享服务**：每个 host 只有一个固定名称的 `codespace-sidecar`，不附属于 project/instance。Atuin 仅经
   宿主 `127.0.0.1:8002` 暴露。sidecar 的 image-prewarm 定时任务是唯一允许 bind-mount 宿主 rootful
   Podman socket 的共享服务，仅按脚本内写死清单预拉镜像与清理 dangling 镜像。sidecar 现由控制面作为
   deployment（`deployments.sidecar`）原生管理，但仍保留手动 `run-*.sh` 与带外 `deploy_sidecar` CLI 等价路径。
7. **平台选择**：project 每个 `host` 条目 `platform` 只能省略或设为 `linux/amd64`、`linux/arm64`；
   省略时库存 label 用 `native`。
8. **文档语言**：说明与约束文档用中文；代码标识、命令、协议名和外部 API 保留原文。
9. **Workspace 加密**：逐 project 可选（控制面 project 字段 `encrypt_workspace`，默认关）。开启时控制面把 host
   实例目录 bind 到密文根 `/workspace.enc` 并注入固定 secret `workspace_crypt_key`（env `WORKSPACE_CRYPT_KEY`，
   对齐 sidecar `atuin_db_uri` 模式，须经 `sync_secrets` 预注册，缺失即 fail-fast）；镜像侧 `workspace-crypt`
   据此用 gocryptfs 把明文挂到 `/workspace`。关闭时直接 bind 明文 `/workspace`、不注入 secret。加密依赖 FUSE
   （`/dev/fuse`）。加密仅作用于 `/workspace`；`/upload`、`/cache` 始终明文 bind 各自宿主根，不受影响。
10. **数据挂载**：每个实例挂载三个宿主目录到 `/workspace`、`/upload`、`/cache`，分别落在独立宿主根
    `~/codespace`、`~/codespace-upload`、`~/codespace-cache` 下的 `<workspace>/<instance>` 子目录（逐实例隔离，
    不跨实例/workspace 共享）。三者均为控制面保留 mount target，用户卷不得占用。
11. **Deployment**：host 级自包含部署容器（sidecar、LLM serving 等），与开发 environment 明确区分：容器名
    确定性 `codespace-<id>`、只带 `codespace.deployment*` label（**绝不带 `codespace.managed`**，与 environment
    inventory 用不相交 filter），无 workspace/SSH 投影/git checkout/provider 凭据。哪些 host 跑它由
    `hosts.<host>.deployments` 决定（host 选 deployment）。持久数据落在独立宿主根 `~/codespace-deployment/<id>`，
    config volume 用 `${DEPLOYMENT_DATA}` 占位符引用；镜像自装产物、运行形态在 `deployments.<id>.container` 声明。

## 变更规则

- 新增工具配置：跨场景 home 配置放 `images/dev/rootfs/home/x/`（容器经 `COPY rootfs/ /` 自动就位），
  非容器场景才需的配置放 `dotfiles/<tool>/`，并在 `dotfiles/setup.sh` 相应 scene 里接线。
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
  [`images/wsl/AGENTS.md`](images/wsl/AGENTS.md)、[`images/llm/AGENTS.md`](images/llm/AGENTS.md)。
- `docs/codespace-image-ghcr-timeout-investigation.md`：多架构镜像访问 GHCR 超时调查记录。

## 已知边界

- `dotfiles/setup.sh` 的 `CONF_PATH` 默认值仍待移除；它还据此推导 `ROOTFS_HOME=<repo>/images/dev/rootfs/home/x`，
  变更前需核对所有调用方与仓库布局假设。
- workflow 中被注释的 matrix 项表示暂停构建，不代表源码已废弃。
