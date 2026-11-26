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
| Node.js runtime 缺失或声明变化 | `platform/macos/maintenance/node-runtime.sh` |
| Node CLI 缺失或版本变化 | `platform/macos/maintenance/node-tools.sh` |
| Go 缺失或版本变化 | `platform/macos/maintenance/go.sh` |
| Rust toolchain 缺失或需要更新 | `platform/macos/maintenance/rust.sh` |
| GNU GCC 或其用户命令链接缺失 | `platform/macos/maintenance/homebrew.sh` |
| 用户明确要求安装或更新 LLVM SDK | `platform/macos/maintenance/llvm.sh` |
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
- LLVM：默认不安装，使用 Xcode 提供的 Apple Clang。用户明确要求时使用 `llvm.sh` 中
  锁定的官方 macOS arm64 archive，按项目选择 PATH；最新 release 缺少对应 artifact 时
  保留已锁定版本，不切换安装来源。
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

用户明确要求首次安装、全量安装或完整收敛时，无条件按以下顺序运行默认操作；
LLVM 仍需单独明确请求：

1. `platform/macos/maintenance/homebrew.sh`
2. `platform/macos/maintenance/binman.sh`
3. `platform/macos/maintenance/uv.sh`
4. `platform/macos/maintenance/python-tools.sh`
5. `platform/macos/maintenance/node-runtime.sh`
6. `platform/macos/maintenance/node-tools.sh`
7. `platform/macos/maintenance/go.sh`
8. `platform/macos/maintenance/rust.sh`
9. `platform/macos/maintenance/java-runtime.sh`
10. `platform/macos/maintenance/java-tools.sh`
11. `platform/macos/maintenance/home-links.sh`
12. `platform/macos/maintenance/default-apps.sh`
13. `platform/macos/maintenance/atuin-daemon.sh`

某一步失败时停止，不运行依赖它的后续步骤。修复后从失败的原子操作继续，不重复执行无关操作。

## Verification

只验证本次操作和其依赖。目标版本、安装布局与 executable 以所属 manifest/maintenance
脚本为准，不维护第二份清单：检查 marker/链接和权限，再用实际命令做 version/help smoke
check；compiler/runtime 变化还需最小编译或执行，不能只检查版本输出。

home 操作验证链接、权限与 SSH include；LaunchAgent 操作验证 launchctl、daemon status、
socket 与日志。不要启用可选的 `sh.atuin.server`。
隔离 HOME 和原生平台验证遵循 `platform/macos/AGENTS.md`；macOS-only 操作不构建 Workspace。
