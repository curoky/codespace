---
description: 在 codespace Workspace 中执行命令、选择工具链、安装依赖或判断持久化路径时使用
alwaysApply: true
---

<!-- markdownlint-disable MD013 -->

# Codespace Workspace

项目数据放在 `/workspace`，文件交换目录是 `/upload`。`/cache` 只保存 IDE
server 的 `bin` 与 `extensions`，不要把 repository、构建产物或普通工具缓存放入
其中。容器重建时不应依赖 `/workspace` 和 `/upload` 之外的可变 filesystem 状态。

执行项目前先读取 repository 自带的 `AGENTS.md`、manifest、lockfile 和 task
入口，优先使用项目声明的 package manager 与工具版本。

默认 shell 环境已包含预装工具。若执行器没有加载 profile 或出现
`command not found`，使用 `zsh -lic '<cmd>'`；需要绕过 shell 初始化时再按下表使用
稳定绝对路径。

## Toolchains

| 场景 | 路径 / 用法 |
| --- | --- |
| Python project | 优先 `uv run <cmd>`；uv 是 `/opt/bm/bin/uv` |
| Python interpreters | `python3` 是 `/opt/uv/bin/python3`；Python 3.9-3.14 用 `uv python find 3.<N>` 定位，不硬编码 architecture path |
| Python tools | `ruff`、`uv` 在 `/opt/bm/bin`；image CLI tools 在 `/opt/uv/bin` |
| Conda | `/opt/conda/condabin/conda`，默认不激活 environment，仅在项目明确使用 Conda 时调用 |
| Java | JDK 25: `JAVA_HOME=/nix/var/nix/profiles/jdk25/lib/openjdk`；JDK 8: `/nix/var/nix/profiles/jdk8/lib/openjdk` |
| Maven | `mvn`，稳定入口 `/nix/var/nix/profiles/default/bin/mvn` |
| Node.js | 默认 Node.js 24；Node.js 26 使用 `/nix/var/nix/profiles/nodejs-26/bin` |
| Node tools | `npm`、`npx`、`corepack`、`pnpm`、`pnpx` 在默认 Nix profile |
| Go | 默认 Go 1.26；稳定入口 `/nix/var/nix/profiles/go-1_26/bin` |
| Go tools | `/opt/bm/profile/go/bin`，包含 `gopls`、`golangci-lint`、`dlv` 等 |
| Rust | `/opt/rust/cargo/bin/cargo`、`rustc`、`clippy`、`rustfmt`、`rust-analyzer` |
| Rust env | 非登录 shell 需 `CARGO_HOME=/opt/rust/cargo RUSTUP_HOME=/opt/rust/rustup` |
| C/C++ | 默认 GCC 15；GCC 12/16 分别在 `/nix/var/nix/profiles/gcc-12/bin` 与 `/nix/var/nix/profiles/gcc-16/bin` |
| Clang tools | `clang-format` 等稳定入口在 `/opt/bm/bin` |
| CUDA | Toolkit 12.2.2；`CUDA_HOME=/usr/local/cuda`，链接到 `/usr/local/cuda-12.2` |
| 构建工具 | `/opt/bm/bin` 下有 `cmake`、`ninja`、`make`、`bazel`、`buildifier`、`task` |
| Protobuf | 多版本仅在 `/opt/bm/store/protobuf_<version>/bin`，按项目要求显式选择 |
| Shell | `/opt/bm/bin/shfmt`、`shellcheck`、`bats` |
| Formatting | `markdownlint-cli2`、`prettier` 在默认 Nix profile；`ruff`、`shfmt`、`nixfmt` 在 `/opt/bm/bin` |
| 常用 CLI | `/opt/bm/bin` 下有 `git`、`gh`、`rg`、`fd`、`jq`、`curl`、`ssh`、`rsync`、`podman` 等 |

## Dependencies

- 修改项目依赖时使用项目已有的 package manager，并同步其 lockfile。
- 临时 Python CLI 使用 `uvx <tool>`；需要保留到当前容器时使用
  `uv tool install <tool>`。
- Node.js 工具优先安装到项目 dev dependencies，不用无版本约束的 global install。
- 安装全局工具默认使用 nixpkgs：临时执行用
  `nix shell nixpkgs#<pkg> -c <cmd>`，安装到用户 profile 用
  `nix-env -iA nixpkgs.<pkg>`。可先用 `nix search nixpkgs <name>` 查包。
- 只有 nixpkgs 不提供所需工具或必须修改 Debian system integration 时才用
  `sudo apt`。运行期全局安装不会跨容器重建持久化；需要长期提供的工具应修改
  Workspace image manifest。

## CUDA

- Image 提供 CUDA Toolkit 12.2.2，固定兼容 NVIDIA 535 系列 driver 支持的 CUDA
  12.2 上限；不要在 Workspace 内替换 `/usr/local/cuda` 或安装另一套 system CUDA。
- `nvcc --version` 查看 toolkit，`nvidia-smi` 查看 Host driver 与已分配 GPU。Toolkit
  存在不代表当前 Workspace 一定分配了 GPU device。
- 编译默认使用 `CUDA_HOME=/usr/local/cuda`，runtime library 位于
  `/usr/local/cuda/lib64`。

## Runtime Services

s6 管理 Workspace 常驻服务。先用 `s6-svstat /run/service/<service>` 查看 longrun
状态，用 `tail -n 200 /var/log/s6.<service>.log` 查看日志；不要另起重复 daemon。

| Service | Endpoint / purpose |
| --- | --- |
| `sshd` | `0.0.0.0:22`，由 Host loopback port 转发 |
| `atuin-server` | `127.0.0.1:8002`，shell history sync |
| `rclone-webdav` | `127.0.0.1:8004`，Workspace/logs 只读，`/upload` 可写 |
| `copyparty-webdav` | `127.0.0.1:8005`，受限 WebDAV/file access |
| `ollama` | 默认 `127.0.0.1:8006` |
| `rclone-http` | `127.0.0.1:8007`，只读 file HTTP |
| `miniserve-http` | `127.0.0.1:8008`，只读 `/var/log` |
| `workspace-agent` | `/run/codespace-control/agent.sock`，control plane bootstrap/status |

`workspace-init`、`home-init`、`gh-login`、`git-config` 和 `atuin-login` 是 s6
oneshot，不应作为普通命令重复执行。服务日志统一位于 `/var/log/s6.*.log`。

## Host Integrations

- GitHub CLI 已由 `gh-login` 完成认证。先用 `gh auth status` 验证，然后直接使用
  `gh issue`、`gh pr`、`gh run` 或 `gh api` 调查和处理 GitHub 问题；不要再次登录、
  打印 token 或读取 secret。
- Host 的 rootful Podman socket 挂载在 `/run/podman/podman.sock`。使用
  `podman --url unix:///run/podman/podman.sock <command>`，或为连续操作设置
  `CONTAINER_HOST=unix:///run/podman/podman.sock`，可从 Workspace 调试 Host
  container。
- Podman socket 等同 Host root 权限。操作前先检查目标的 name、label 与状态，不运行
  `podman system prune`，不删除或重启与当前任务无关的 container、image、volume 或
  network。
