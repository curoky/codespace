# macOS Platform

## Scope

拥有当前用户的 Homebrew、用户级开发工具、macOS-specific home source、LaunchAgent、
默认应用与 client SSH wiring。维护 Skill 按 actual state 编排独立脚本，不使用统一 installer。

## Contracts

- `Brewfile` 声明完整 Homebrew state；`homebrew.sh` 执行 bootstrap 与
  `brew bundle --force-cleanup`，manifest 外 formula/cask 会被删除。GNU GCC 由 Homebrew
  管理，无后缀命令链接到用户 bin，不替换 Apple compiler。
- `binman.yaml` 声明用户级 standalone tools；`binman.sh` bootstrap 并建立 alias。
  runtime 与语言 CLI 分别维护，优先使用 package manager 原生能力，否则重建受管目录。
- 每个 maintenance 脚本独立完成一个可重复操作，不 source/call 同目录其他脚本，不扫描
  未声明路径。依赖缺失直接失败，顺序由 `manage-macos-environment` Skill 负责。
- 默认 runtime、CLI binding、profile 与 editor 路径一致；可移植 Node/Python CLI 与
  Workspace 对齐。切换 Shell PATH 不会改变已安装 CLI 的 binding，变更后重装对应 CLI。
- Node/Java helper 来自本仓库 GHCR 的 macOS arm64 artifact，使用 ORAS 下载，不要求本地
  compiler 或容器引擎。Java helper 本身不安装 distribution，也不要求预装 JDK。
- Temurin archive 提取 `Contents/Home`，使用 Linux runtime 根布局，不注册系统 JDK。
  Go/LLVM 保留精确版本目录，通过 minor/major 相对链接提供稳定入口，复用时也维护链接。
- uv 管理 Python runtime 与隔离 CLI，使用原生默认选项提供 python/python3，CLI 显式绑定
  同一 interpreter；不改 uv metadata，cache 与项目 virtualenv 保持原生位置。
- rustup/SDK 根独立于运行期 `CARGO_HOME`；用户 `~/.cargo` 保留 CLI 与 cache。
  archive 精确锁定并校验，Rust SDK 不使用浮动 channel，项目覆盖在 Shell 加载后设置。
- macOS-specific source 位于 `rootfs/Users/x/`；共享 dotfile 与 SSH material 由
  `home-links.sh` 链接 Workspace source。默认 source 权限为 0600，可执行内容显式 0755；
  仅目标需要独立 inode、权限或运行期修改时 copy。
- 容器与 macOS 的 AI 规则保持一致结构；使用约定变化同步对应规则，不额外安装软件管理 Skill。
- 静态 client SSH config、key 与 known_hosts 来自声明 source；动态 Workspace route
  由控制面发布，home links 只准备目录与 include。
- LaunchAgent 由对应脚本 copy/reload，不隐式启用可选 service。维护不创建 Podman machine
  或构建 Workspace image；macOS 本地 Podman 只属于用户显式操作。

## Pitfalls

- LLVM 官方最新 release 缺少 macOS arm64 artifact 时保留锁定版本，不换来源或自行构建。
- Snipaste `last_save_folder` 的 tilde 展开未获官方说明或原生验证，保留绝对路径；
  launchd 不展开变量，plist 路径也保留绝对值，不加 Shell wrapper。
- CI 在 Apple Silicon 原生检查，并在工具发布成功后从空用户目录验证安装，避免下载旧产物。
  macOS 环境与共享 home 的 push 先触发工具发布，再由成功事件触发安装验证；PR 仅做
  contract 检查，不从 registry 安装工具。
  CI 不安装 GUI cask 或修改默认应用；第三方 cask 的信任声明放 tap 的 `trusted.casks`，
  因 Bundle 跳过 cask 时仍需应用。Bundle 的 cask list 只给短名，第三方 cask 必须声明 tap。

## Validation

`bats platform/macos/tests` 使用隔离 HOME 检查操作、权限与 SSH 结构；不替代原生 macOS
验证。plist 变化运行 `plutil -lint`，Swift setup 变化执行对应 script。
macOS-only 变化不构建 Workspace；共享 source/artifact 变化按根索引联动。
原生安装验证入口是 `.github/workflows/check-macos.yaml` 与维护 Skill。
GitHub Actions step 的环境独立；切换 HOME 后须显式把该用户的安装期依赖加入 PATH，
launcher 验证再通过项目 runtime 的 PATH 检查固定 binding。
