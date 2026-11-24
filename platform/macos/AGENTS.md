# macOS Platform

此目录拥有唯一 client 环境：当前用户的 Homebrew、`$HOME` 下的开发工具、macOS-specific
home source、LaunchAgent、默认应用和控制面 SSH wiring。`.agents/skills/manage-macos-environment`
根据 actual state 调用独立维护脚本，不使用镜像构建或统一 installer。

## Ownership

- `Brewfile` 是完整 Homebrew state；`maintenance/homebrew.sh` 负责 Homebrew bootstrap 和
  `brew bundle --force-cleanup`，manifest 外 formula/cask 会被删除。新增或移除软件只改
  manifest，不增加零散 brew 命令。
- `binman.yaml` 声明安装到 `~/.local` 的 standalone tools，与 Workspace 的 `/usr/local`
  布局对应；`maintenance/binman.sh` 在线 bootstrap binman、按 manifest 安装并建立 alias。
- `maintenance/` 中每个脚本拥有一个可独立收敛的 host 操作。runtime 与 CLI 分别维护，
  脚本不 source 或调用同目录其他脚本；复用 Workspace 的 `node-tool` 与 `java-tool`，
  依赖关系只由 Skill 编排。
- `rootfs/Users/x/` 只保存 macOS-specific source。跨 macOS/Workspace 共用的 dotfile 和 SSH
  material 由 `maintenance/home-links.sh` 链接 `platform/container/workspace/rootfs/home/x/`。
- `rootfs/Users/x/.codex/AGENTS.md` 以中文约束 macOS Agent 使用用户级工具链与声明式维护
  入口，内容结构与 Workspace 全局规则保持一致；macOS 不额外安装软件管理 Skill。
- `scripts/` 保存原子操作调用的实现资产或非环境维护工具；`tests/` 用隔离 HOME 验证
  maintenance 操作、权限与 SSH 结构。

## Maintenance Contracts

- 每个脚本直接执行时完成一个操作，必须可重复运行；不要新增全量安装入口、共享 helper
  framework、bundle、发布 workflow 或脚本间隐式调用。少量重复优先于跨操作抽象。
- 优先复用软件或包管理器原生的简单维护能力；否则直接重建受管安装目录，不自建复杂的
  增量更新或局部修复策略。不得扫描或清理未声明的用户路径；依赖缺失时直接失败，由
  Skill 先运行对应依赖操作。
- 默认 Node.js runtime、Node CLI 的 runtime binding 与 editor npm 路径保持一致；已有
  CLI 不随 Shell PATH 切换，binding 变化时由 Skill 编排对应 package 的重装。
- `maintenance/node-tools.sh` 的默认 Node CLI 与 Workspace 保持一致。
- JDK 从 Temurin archive 提取 `Contents/Home`，采用 Linux 的 runtime 根布局，不注册
  系统 JDK；Shell 与 editor 使用同一 runtime。
- Python runtime 与隔离 CLI 由 uv 管理，使用 `UV_*_DIR` 指定用户级软件目录；缓存与项目
  virtualenv 保持原生位置，不手工改写 uv metadata 或 interpreter binding。
- `maintenance/python-tools.sh` 使用 Workspace 的 `config/python-tools.txt` 声明可移植
  Python CLI，不通过 Homebrew 或 binman 重复安装。
- rustup 与 SDK 安装根独立于用户的 `CARGO_HOME`；安装阶段的 Cargo 根只提供工具链入口，
  运行期 `~/.cargo` 保留用户 CLI 与缓存。
- home link source 默认为 `0600`；可执行 source 必须显式声明 `0755`。只有目标需要独立
  inode、权限或运行期修改时才 copy。应用配置只使用该字段原生支持的路径语法，不增加
  安装时模板替换。
- 路径展开按应用的具体字段核实，不从其他字段推断。Snipaste `last_save_folder` 的 `~`
  展开未获官方说明或原生验证，当前保留绝对路径。
- client SSH 的静态 include/config、login key 和 known_hosts 来自声明 source；Workspace
  动态 route 由控制面写入 `~/.ssh/codespace/workspaces/`，home links 只准备目录和 include。
- LaunchAgent source 位于 rootfs，由对应 maintenance 脚本 copy 并重新加载。launchd
  自身不展开变量，相关路径保留绝对值，不增加 Shell 包装。不要隐式启用可选 service。
- macOS maintenance 不启动或创建 Podman machine，也不构建 Workspace image；控制面连接
  Linux remote Host，macOS 本地 Podman 只属于用户显式操作。

## Validation

```bash
bats platform/macos/tests
```

修改 plist 时额外运行 `plutil -lint <plist>`；修改 Swift setup 时执行对应 script。macOS-only
变更不构建 Workspace image；修改共享 home、SSH trust material 或 container artifact 时才按
对应模块要求构建。完成后运行 `task check:full`。

`.github/workflows/check-macos.yaml` 在 Apple Silicon runner 上执行原生 contract 检查；push、
定时和手动运行还会从空的 `/Users/x` 安装用户级工具链、home config 与 Atuin daemon。CI
通过 Bundle 安装 formula 与 tap，跳过全部 cask 后再逐项检查。第三方 cask 的信任声明放在
tap 的 `trusted.casks` 中，使跳过 cask 安装时仍会应用；`brew bundle list --cask` 输出
短名称，第三方 cask 必须显式声明其 tap。CI 不安装 GUI cask，也不修改 runner 的默认应用关联。
