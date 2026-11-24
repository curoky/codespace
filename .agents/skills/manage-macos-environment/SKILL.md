---
name: manage-macos-environment
description: 增量或全量安装并持续维护本项目的 macOS 开发环境。用户要求新增、升级、修复、同步或检查本机开发工具和后台服务时调用；不用于 Workspace 镜像。
---

# Maintain macOS Environment

从仓库根目录执行，先读 `platform/macos/AGENTS.md`。

## Incremental Install

默认执行增量安装。先检查 actual state，只运行目标操作及其缺失依赖。脚本之间不互相调用，
依赖顺序由本 Skill 负责。

| 状态 | 操作 |
| --- | --- |
| Homebrew 或 Brewfile state 缺失 | `platform/macos/maintenance/homebrew.sh` |
| standalone tools 缺失或 manifest 变化 | `platform/macos/maintenance/binman.sh` |
| uv 默认 Python 缺失或声明变化 | `platform/macos/maintenance/uv.sh` |
| Python CLI 缺失或声明变化 | `platform/macos/maintenance/python-tools.sh` |
| Node.js 24/26 缺失或版本变化 | `platform/macos/maintenance/node-runtime.sh` |
| Node CLI 缺失或版本变化 | `platform/macos/maintenance/node-tools.sh` |
| Go 缺失或版本变化 | `platform/macos/maintenance/go.sh` |
| Rust toolchain 缺失或需要更新 | `platform/macos/maintenance/rust.sh` |
| GNU GCC 或其用户命令链接缺失 | `platform/macos/maintenance/homebrew.sh` |
| LLVM SDK 缺失或声明变化 | `platform/macos/maintenance/llvm.sh` |
| Java 缺失或版本变化 | `platform/macos/maintenance/java-runtime.sh` |
| java-tool 缺失或发布产物变化 | `platform/macos/maintenance/java-tools.sh` |
| home links 或 copied config 缺失 | `platform/macos/maintenance/home-links.sh` |
| 默认应用关联需要重置 | `platform/macos/maintenance/default-apps.sh` |
| Atuin daemon 缺失或需要重载 | `platform/macos/maintenance/atuin-daemon.sh` |

新增软件时先确定 ownership：

- standalone CLI：修改 `platform/macos/binman.yaml`，运行 `binman.sh`。
- macOS formula 或 GUI application：修改 `platform/macos/Brewfile`，运行 `homebrew.sh`。
- 可移植 Python CLI：修改 `platform/macos/maintenance/python-tools.sh` 与 Workspace
  `Dockerfile`，运行 `python-tools.sh`。
- Python runtime 及其他语言的 runtime 与 CLI：修改对应 maintenance 脚本，运行该脚本。
- GNU GCC：由 `Brewfile` 声明，运行 `homebrew.sh`；其无后缀命令由该操作链接到用户 bin。
- LLVM：使用 `llvm.sh` 中锁定的官方 macOS arm64 archive；最新 release 缺少对应 artifact
  时保留已锁定版本，不切换安装来源。
- home config 或 LaunchAgent：修改 rootfs source，再运行 `home-links.sh` 或对应 service 脚本。

增量依赖：

- `uv.sh` 依赖 `binman.sh` 提供 uv。
- `python-tools.sh` 依赖 `binman.sh` 与 `uv.sh`。
- `node-tools.sh` 依赖 `binman.sh` 提供 ORAS、pnpm，以及 `node-runtime.sh`。
- `java-tools.sh` 依赖 `binman.sh` 提供 ORAS；不默认安装 Java CLI package。
- `atuin-daemon.sh` 依赖 `binman.sh` 提供 Atuin。

不要用临时 `brew install`、全局 `npm install`、全局 `pnpm add` 或手工复制文件替代这些脚本。
软件声明变化时先修改对应 manifest 或脚本，再运行该操作。

`node-tools.sh` 整体重建受管 helper 与 CLI 目录。Node CLI 的 runtime binding 变化时重新
运行该操作；仅改变 Shell PATH 不会更新已有 launcher 的 binding。

## Full Install

用户明确要求首次安装、全量安装或完整收敛时，无条件按以下顺序运行全部操作：

1. `platform/macos/maintenance/homebrew.sh`
2. `platform/macos/maintenance/binman.sh`
3. `platform/macos/maintenance/uv.sh`
4. `platform/macos/maintenance/python-tools.sh`
5. `platform/macos/maintenance/node-runtime.sh`
6. `platform/macos/maintenance/node-tools.sh`
7. `platform/macos/maintenance/go.sh`
8. `platform/macos/maintenance/rust.sh`
9. `platform/macos/maintenance/llvm.sh`
10. `platform/macos/maintenance/java-runtime.sh`
11. `platform/macos/maintenance/java-tools.sh`
12. `platform/macos/maintenance/home-links.sh`
13. `platform/macos/maintenance/default-apps.sh`
14. `platform/macos/maintenance/atuin-daemon.sh`

某一步失败时停止，不运行依赖它的后续步骤。修复后从失败的原子操作继续，不重复执行无关操作。

## Verification

每次操作后验证其直接产物：

```bash
test -x "$HOME/.local/bin/uv"
test -x "$HOME/.local/bin/pnpm"
"$HOME/.local/opt/uv/bin/python" --version
"$HOME/.local/opt/uv/bin/python3" --version
"$HOME/.local/opt/uv/bin/copyparty" --help
"$HOME/.local/opt/uv/bin/licenseheaders" --help
"$HOME/.local/opt/uv/bin/netron" --help
"$HOME/.local/opt/uv/bin/mitmdump" --version
"$HOME/.local/opt/uv/bin/git-filter-repo" --version
test -x "$HOME/.local/opt/node/nodejs24/bin/node"
test -x "$HOME/.local/opt/node/nodejs26/bin/node"
test -x "$HOME/.local/opt/node/tools/bin/prettier"
"$HOME/.local/opt/node/tools/bin/defuddle" --help
"$HOME/.local/opt/node/tools/bin/markdownlint-cli2" --version
"$HOME/.local/opt/node/node-tool" --help
test -x "$HOME/.local/opt/go/go1.27/bin/go"
"$HOME/.local/opt/node/nodejs26/bin/node" --version
"$HOME/.local/opt/go/go1.27/bin/go" version
CARGO_HOME="$HOME/.cargo" RUSTUP_HOME="$HOME/.local/opt/rust/rustup" \
  "$HOME/.local/opt/rust/cargo/bin/rustc" --version
CARGO_HOME="$HOME/.cargo" RUSTUP_HOME="$HOME/.local/opt/rust/rustup" \
  "$HOME/.local/opt/rust/cargo/bin/rustup" component list --installed
"$HOME/.local/opt/llvm/llvm23/bin/clang" --version
"$HOME/.local/opt/llvm/llvm23/bin/clang-format" --version
"$HOME/.local/bin/gcc" --version
"$HOME/.local/bin/g++" --version
"$HOME/.local/opt/java/openjdk27/bin/java" -version
"$HOME/.local/opt/java/openjdk27/bin/javac" -version
"$HOME/.local/opt/java/java-tool" --help
test -L "$HOME/.zshrc"

domain="gui/$(id -u)"
launchctl print "$domain/sh.atuin.daemon"
atuin daemon status
test -S "$HOME/.local/share/atuin/atuin.sock"
tail -n 100 /tmp/atuin.daemon.log
```

只验证本次操作和其依赖，不因 macOS-only 维护构建 Workspace 镜像。修改共享 Workspace
source 或 container artifact 时，再按对应目录 `AGENTS.md` 验证。不要启用可选的
`sh.atuin.server`。
