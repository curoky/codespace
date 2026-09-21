---
description: 在 Codespace Workspace 容器内操作项目、选择工具链或诊断环境时使用
alwaysApply: true
---

<!-- markdownlint-disable MD013 -->

# Workspace Container

先读取 repository 的 `AGENTS.md`、manifest、lockfile 和 task 入口；项目约定优先。

## Runtime

- 默认用户是 `x`（UID/GID 5230）。`sudo` 验证运行时 secret 设置的 root 密码，不提供免密提权。
- repository 和持久数据放 `/workspace`，交换文件放 `/upload`；不要依赖 container layer、
  `/tmp` 或普通 `$HOME` 路径持久化。
- s6 管理常驻服务，不要重复启动 SSH、Ollama、file server、Atuin 或 Workspace Agent。
- 不修改 `/opt/codespace`、`/etc/s6`、`/run/codespace-control` 或 IDE cache mount，除非任务
  是开发 Workspace image。
- Workspace 不挂载 Host Podman socket。不要设置 `CONTAINER_HOST`、
  `CONTAINER_CONNECTION` 或 `DOCKER_HOST` 连接 `/run/podman/podman.sock`。

## Filesystem

| Path | Usage |
| --- | --- |
| `/workspace` | 项目数据；encrypted Workspace 的透明明文视图 |
| `/workspace.enc` | gocryptfs backing store，不直接操作 |
| `/upload` | 可读写文件交换目录 |
| `/opt/secret` | secret Service 提供的 credential view，只读取任务所需文件 |
| `/run/secrets` | Podman 启动 secret，不输出或复制 |
| `/run/codespace-control` | Workspace Agent socket，不存用户数据 |
| `/var/log` | s6 服务日志 |

镜像不提供 `/cache`。持久 IDE cache 直接挂载在
`/home/x/{.vscode-server,.trae,.trae-cn,.trae-server,.trae-cn-server}` 的受管子目录。

## Toolchains

交互 shell 是 zsh。非登录执行器缺少环境或命令时使用 `zsh -lic '<command>'`。

| Stack | Version / location |
| --- | --- |
| Python | uv-managed 3.9-3.14，默认 3.14；优先 `uv run`，用 `uv python find 3.<N>` 定位解释器 |
| Conda | `/opt/conda/condabin/conda`，默认不激活 environment |
| Node.js | 默认 24；26 在 `/nix/var/nix/profiles/nodejs-26/bin` |
| Go | 默认 1.26；tools 在 `/usr/local/profile/go/bin` |
| Rust | `/opt/rust/cargo/bin`；非登录 shell 设置 `CARGO_HOME=/opt/rust/cargo RUSTUP_HOME=/opt/rust/rustup` |
| Java | JDK 25 默认；JDK 8/25 分别在 `/nix/var/nix/profiles/jdk{8,25}/lib/openjdk` |
| C/C++ | GCC 15 默认；GCC 12/16 在 `/nix/var/nix/profiles/gcc-{12,16}/bin`；Clang tools 在 `/usr/local/bin` |
| CUDA | 12.2.2，`CUDA_HOME=/usr/local/cuda`；已安装 Nsight Systems/Compute |

镜像预装的 CLI、build、format 和 lint 工具主要位于 `/usr/local/bin` 或默认 Nix profile；
`x` 通过 `bm install` 安装的工具位于 `/opt/bm` 并优先于预装版本。Protobuf 不在默认 PATH，
按项目版本使用 `/usr/local/store/protobuf_<version>/bin`。

依赖安装顺序：

1. 使用项目现有 package manager 并同步 lockfile。
2. 临时 Python CLI 使用 `uvx`；Node 工具加入项目 `devDependencies`。
3. 通用临时工具使用 `nix shell nixpkgs#<package> -c <command>`。
4. 仅在必须修改 Debian integration 时使用 `sudo apt`。

需要跨 container 重建保留的通用工具应加入 Workspace image。

## Services

除 SSH 外，服务只监听 container loopback；外部访问需要 Project `tunnel_ports`。

| Service | Endpoint |
| --- | --- |
| `sshd` | `0.0.0.0:22` |
| `atuin-server` | `127.0.0.1:8002` |
| `rclone-webdav` | `127.0.0.1:8004` |
| `copyparty-webdav` | `127.0.0.1:8005` |
| `ollama` | `127.0.0.1:8006` |
| `rclone-http` | `127.0.0.1:8007` |
| `miniserve-http` | `127.0.0.1:8008` |
| `nixcache` | `127.0.0.1:8009` |
| `workspace-agent` | `/run/codespace-control/agent.sock` |

```bash
s6-svstat /run/service/<service>
tail -n 200 /var/log/s6.<service>.log
```

`workspace-init`、`home-init`、`hosts-blackhole`、`git-config`、`gh-login`、
`atuin-login` 和 `secret-mount` 是启动期 oneshot，不要重复运行。`/opt/secret` mount 失败时
检查 `/var/log/s6.secret-mount.log`，确认 secret Service 可达后用 `mount-secret` 重试。

## Rootless Podman

- 直接使用 `podman build/run/...`；需要 Docker-compatible CLI 时使用 `docker`。
- 数据位于 `/opt/podman/data`，只有 Project 显式挂载 Host 目录时才持久。不要修改或
  删除其中的 storage 数据，也不要递归修改 ownership。
- 服务由 s6 管理，不要自行启动；内部 container 共用 Workspace 的资源边界。

服务异常时检查：

```bash
s6-svstat /run/service/podman
tail -n 200 /var/log/s6.podman.log
podman info --format 'rootless={{.Host.Security.Rootless}} driver={{.Store.GraphDriverName}}'
```

## Credentials And Network

- 使用 GitHub CLI 前运行 `gh auth status`；不要重新登录、读取或输出 token。
- `KRB5CCNAME=/opt/secret/krb5_ccache`。不要输出 `/run/secrets`、`/opt/secret`、private
  key 或完整环境；只检查存在性、权限、mount 和退出码。
- encrypted Workspace 缺少 key 时启动失败，不回退 plaintext；不要 unmount `/workspace`。
- container 间使用 control plane DNS name，如 `codespace-service-secret`，不要使用动态 IP。
- 不要把当前 proxy 写入 repository。新增 Host/macOS 入口须配置 `tunnel_ports`。
- GPU 任务先运行 `nvidia-smi`，再运行 `nvcc --version`；不要替换 system CUDA。
