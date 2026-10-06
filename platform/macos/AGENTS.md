# macOS Platform

此目录拥有唯一 client 环境：固定 `/Users/x` 的 Homebrew/binman 工具、macOS-specific home
source、LaunchAgent、默认应用和控制面 SSH wiring。`install.sh` 必须可重复执行并收敛到声明
状态。

## Ownership

- `Brewfile` 是完整 Homebrew state；installer 使用 `brew bundle --force-cleanup`，manifest
  外 formula/cask 会被删除。新增或移除软件只改 manifest，不在 installer 增加零散 brew
  命令。
- `binman.yaml` 声明 `/opt/bm` 中的 standalone tools；`install.sh` 只负责 bootstrap binman、
  按 manifest 安装和建立必要 alias。
- `scripts/build-bm-bundle.sh` 在 Darwin/arm64 上将 `binman.yaml` 组装成可迁移的 `bm/`
  archive；`publish-macos.yaml` 将其作为单层 OCI artifact 发布到 GHCR，并在独立 hosted
  macOS job 中验证完整装机。
- `install-v2.sh` 复用现有 installer，但从 GHCR 下载、校验并替换 `/opt/bm`；默认读取
  `macos-bm-darwin-arm64` tag，CI 通过 `CODESPACE_BM_REFERENCE` 固定到本次发布的 digest。
- `rootfs/Users/x/` 只保存 macOS-specific source。跨 macOS/Workspace 共用的 dotfile 和 SSH
  material 由 installer 链接 `platform/container/workspace/rootfs/home/x/`。
- `scripts/` 拥有 macOS imperative setup；`tests/` 用隔离 HOME 验证 link/copy、权限与 SSH
  结构。

## Installer Contracts

- `link_home_path` 用于应随仓库 source 立即变化的配置；`copy_home_path` 只用于目标必须拥有
  独立 inode、权限或运行期可变内容的文件。新增 home path 时明确选择其 ownership。
- installer 可以替换它明确管理的目标，但不得扫描或清理未声明的用户路径。source file 在
  link 前按 credential-like `0600` contract 处理。
- client SSH 的静态 include/config、login key 和 known_hosts 来自声明 source；Workspace
  动态 route 由控制面写入 `~/.ssh/codespace/workspaces/`，installer 只准备目录和 include。
- LaunchAgent source 位于 rootfs，安装时 copy 到用户目录后用 `launchctl` 重新加载。可选
  daemon 必须通过显式 `load_launch_agent` 调用启用。
- installer 不启动或创建 Podman machine；控制面连接 Linux remote Host，macOS 本地 Podman
  只属于用户显式操作。

## Validation

```bash
bats platform/macos/tests
```

修改 plist 时额外运行 `plutil -lint <plist>`；修改 Swift setup 时执行对应 script；共享 home
或 SSH trust material 变化时同时构建 Workspace image。完成后运行 `task check:full`。
