---
description: 在 Codespace Workspace 中开发、选择工具链、运行服务或排查环境
alwaysApply: true
---

<!-- markdownlint-disable MD013 -->

# Codespace Workspace Usage

## Workspace And Persistence

- 默认以用户 `x` 工作，不假设 `sudo` 可用。
- 只在 `/workspace` 保存项目修改和持久产物；容器重建后其他普通 filesystem 路径不保证保留。
- `/opt/resource` 是只读工具 payload；`/opt/{go,rust,llvm,java,node,nvidia}` 和
  `/usr/local/cuda-12.2` 等路径指向它，不要修改或替换这些链接。

## Software Discovery And Installation

- 项目依赖和 runtime 版本遵循 manifest、lockfile 与 toolchain 配置，不要全局安装项目依赖。
- 先用 `command -v <command>` 查找已有 command；镜像预装 command 主要位于
  `/usr/local/bin`、`/usr/local/profile/*/bin`、`/opt/uv/bin`、`/opt/java/tools/bin` 和
  `/opt/node/tools/bin`。
- 缺少时，用 `nix-env -qaP '.*<keyword>.*'` 查询当前 Nix channel，并根据 package 名称、描述
  和上游资料确认 `nixpkgs.<attribute>`，不要反复试装猜测。在进度更新中说明用途后，运行
  `nix-env -iA nixpkgs.<attribute>`；再用 `command -v` 和无副作用的 `--version`、`--help` 或
  smoke test 验证。package name 与 command name 可能不同，以实际安装内容为准。
- 不使用 `sudo`、`apt` 或 `curl | sh`，不修改 `/opt/resource`、`/usr/local` 或 image-managed
  link。

## Toolchain Selection

| Stack | Default | Alternatives And Selection |
| --- | --- | --- |
| Python | `uv`；Python 3.9-3.14 位于 `/opt/uv/python` | 用 `uv python find 3.<N>` 选择解释器；仅在项目明确要求时使用 `/opt/conda` |
| C/C++ | Nix default profile 中的 GCC 15 | Clang 23 位于 `/opt/llvm/llvm23.1.2/bin` |
| Java | JDK 27，`JAVA_HOME=/opt/java/openjdk27` | JDK 8 位于 `/opt/java/openjdk8`；切换时同时更新 `JAVA_HOME` 和 `PATH` |
| Node.js | Node.js 24，位于 `/opt/node/nodejs24` | Node.js 26 位于 `/opt/node/nodejs26`；把选定版本的 `bin` 放到 `PATH` 前部 |
| Go | Go 1.27.1，位于 `/opt/go/go1.27.1` | Go tools 位于 `/usr/local/profile/go/bin` |
| Rust | rustup stable，位于 `/opt/rust` | Cargo executable 位于 `/opt/rust/cargo/bin` |
| CUDA | CUDA 12.2.2，默认链接 `/usr/local/cuda` | Toolkit 位于 `/usr/local/cuda-12.2` |

保留 `/etc/profile.d/app.sh` 设置的 `UV_TOOL_DIR`、`UV_TOOL_BIN_DIR`、
`UV_PYTHON_INSTALL_DIR`、`UV_PYTHON_BIN_DIR`、`CARGO_HOME` 和 `RUSTUP_HOME`，不要 unset、重设
或用命令参数覆盖。

## Managed Services

- Workspace 使用 s6，不运行 systemd；用 `s6-svstat /run/service/<service>` 查看状态，
  `tail /var/log/s6.<service>.log` 查看日志，不要调用 `systemctl`。

## Container Builds

- Podman 是用户 `x` 专用的 rootless runtime，固定连接
  `unix:///run/user/5230/podman/podman.sock`，state 位于 `/opt/podman/data`；不要连接或管理 Host
  Podman。
- 直接使用 `podman build` 和 `podman run`。内部 container 禁用 cgroups，不要依赖 cgroup
  resource limit；rootless build 因 Host cgroup 环境失败时，使用
  `buildah bud --isolation=chroot <build-context>`。

## GitHub Authentication

- `gh` 默认使用 `/run/secrets/github_token_public_read`，用于公开仓库的只读操作。查询 GitHub
  Actions 等需要额外权限的操作时，仅为该命令显式设置 token：

  ```bash
  GH_TOKEN="$(cat /run/secrets/github_token_all_action_rw)" gh run view --log-failed
  ```
