---
alwaysApply: true
---

# macOS Environment

- 工具环境缺失时加载 `~/.zshrc`；项目工具链覆盖在加载后设置。
- 默认语言工具链使用已安装的最新稳定版，项目显式选择在加载环境后设置。
- Python 环境与项目依赖使用 uv，按需用 `--python` 选择
  `~/.local/opt/uv/python` 中的版本；默认 `python` 与 `python3` 指向受管 runtime。
  全局 Python CLI 使用 `uv tool`，不使用全局 pip。
- Node.js 优先使用 26；按项目需求从 `~/.local/opt/node/nodejs*` 选择版本，将其 `bin`
  放到 PATH 首位。
- Node.js 全局 CLI 用 `node-tool` 安装到 `~/.local/opt/node/tools`，不使用全局 npm 或 pnpm 安装。
- Go runtime 位于 `~/.local/opt/go`，用户安装的 Go 命令位于 `~/go/bin`。
- macOS 默认使用 Xcode 提供的 Apple Clang、SDK 与系统工具，不安装 LLVM SDK。
  用户明确要求 LLVM 时使用官方 macOS arm64 archive，安装到 `~/.local/opt/llvm` 并按项目
  选择 PATH；最新 release 缺少对应 artifact 时保留已锁定版本。GNU GCC 由 Homebrew 管理，
  用户 bin 中的 `gcc`、`g++` 链接到 GNU GCC，不替换系统 compiler。
- Rust 工具链由 rustup 管理，位于 `~/.local/opt/rust`；`~/.cargo` 保留用户 CLI 与缓存。
- Java runtime 位于 `~/.local/opt/java/openjdk*`；切换时同步设置 `JAVA_HOME` 与 PATH。
  Java CLI 用 `java-tool` 安装到 `~/.local/opt/java/tools`，不使用 Homebrew 安装 JDK。
- standalone tools 由 `platform/macos/binman.yaml` 声明并安装到 `~/.local`；Homebrew 软件
  由 `platform/macos/Brewfile` 声明。
- 缺少系统软件、全局 CLI 或 runtime 时，说明用途并使用
  `.agents/skills/manage-macos-environment` 中对应的 maintenance 操作，不执行未声明的临时安装。
