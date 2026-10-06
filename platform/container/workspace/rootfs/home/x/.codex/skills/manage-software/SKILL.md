---
name: manage-software
description: >-
  查找本机已安装的 command、选择 runtime 或 toolchain，并在缺少系统软件时通过用户 Nix
  profile 安装；当 command not found、需要确认工具路径或版本、安装 CLI 或切换语言 runtime
  时调用。
---

# Manage Software

## Discover Software

- 以项目 manifest、lockfile 和 toolchain 配置声明的依赖或 runtime 版本为准，不要把项目依赖
  安装成全局软件。
- 先运行 `command -v <command>`。预装 command 主要位于 `/usr/local/bin`、
  `/usr/local/profile/*/bin`、`/opt/uv/bin`、`/opt/resource/opt/uv/bin`、
  `/opt/resource/opt/java/tools/bin` 和 `/opt/resource/opt/node/tools/bin`。
- 把 `/opt/resource`、`/opt/{go,rust,llvm,nvidia}`、Java/Node runtime link 和
  `/usr/local/cuda-12.2` 当作只读内容，不要修改或替换。`java-tool`、`node-tool` 运行期增量
  安装分别写入 `/opt/java/tools`、`/opt/node/tools`。

## Select A Toolchain

| Stack | Default | Alternatives And Selection |
| --- | --- | --- |
| Python | `uv`；Python 3.14 随 Workspace 提供，3.9-3.13 由 resource 提供 | 主版本使用 `/opt/uv/python/cpython-3.14-linux-x86_64-gnu/bin/python3.14`，其他版本使用 `/opt/resource/opt/uv/python/cpython-3.<N>-linux-x86_64-gnu/bin/python3.<N>`；仅在项目明确要求时使用 `/opt/conda` |
| C/C++ | Nix default profile 中的 GCC 15 | Clang 23 位于 `/opt/llvm/llvm23.1.2/bin` |
| Java | JDK 27，`JAVA_HOME=/opt/java/openjdk27` | JDK 8 位于 `/opt/java/openjdk8`；切换时同时更新 `JAVA_HOME` 和 `PATH` |
| Node.js | Node.js 24，位于 `/opt/node/nodejs24` | Node.js 26 位于 `/opt/node/nodejs26`；把选定版本的 `bin` 放到 `PATH` 前部 |
| Go | Go 1.27.1，位于 `/opt/go/go1.27.1` | Go tools 位于 `/usr/local/profile/go/bin` |
| Rust | rustup stable，位于 `/opt/rust` | Cargo executable 位于 `/opt/rust/cargo/bin` |
| CUDA | CUDA 12.2.2，默认链接 `/usr/local/cuda` | Toolkit 位于 `/usr/local/cuda-12.2` |

保留 `/etc/profile.d/app.sh` 设置的 `UV_TOOL_DIR`、`UV_TOOL_BIN_DIR`、
`UV_PYTHON_INSTALL_DIR`、`UV_PYTHON_BIN_DIR`、`CARGO_HOME` 和 `RUSTUP_HOME`；不要 unset、
重设或用命令参数覆盖。

## Install Missing Software

1. 运行 `nix-env -qaP '.*<keyword>.*'` 查询当前 Nix channel。
2. 根据 package 名称、描述和上游资料确认准确的 `nixpkgs.<attribute>`，不要反复试装猜测。
3. 在进度更新中说明需要的软件及用途，然后运行
   `nix-env -iA nixpkgs.<attribute>`。
4. 用 `command -v <command>` 确认实际路径，再运行无副作用的 `--version`、`--help` 或
   smoke test。package name 与 command name 可能不同，以实际安装内容为准。

不要使用 `sudo`、`apt` 或 `curl | sh` 安装软件，也不要修改 `/usr/local` 或其他系统提供的
只读路径。
