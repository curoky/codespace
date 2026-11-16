# macOS 开发环境

- 工具环境缺失时加载 `~/.zshrc`；项目工具链覆盖在加载后设置。
- Python 环境与项目依赖使用 uv，按需用 `--python` 选择
  `~/.local/share/uv/python` 中的版本。
- 切换 Node.js 时，从 `~/.local/share/node/nodejs*` 选择版本，将其 `bin` 放到当前命令的
  PATH 首位。
- Node.js 全局 CLI 位于 `~/.local/share/node/tools`，不使用全局 npm 或 pnpm 安装。
- Go runtime 位于 `~/.local/share/go`，用户安装的 Go 命令位于 `~/go/bin`。
- standalone tools 由 `platform/macos/binman.yaml` 声明并安装到 `~/.local`；Homebrew 软件
  由 `platform/macos/Brewfile` 声明。
- 缺少系统软件、全局 CLI 或 runtime 时，说明用途并使用
  `.agents/skills/manage-macos-environment` 中对应的 maintenance 操作，不执行未声明的临时安装。
