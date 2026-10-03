# macOS Platform

- `rootfs/Users/x/` 只保存 macOS 专属 source；与 Workspace 共用的配置由 installer 直接
  链接 `platform/container/workspace/rootfs/home/x/`，需要独立权限或运行期修改的文件
  才 copy。
- `Brewfile` 是完整 Homebrew 状态；`brew bundle --force-cleanup` 会删除 manifest 外依赖。
- 可选 daemon 必须显式启用；installer 不负责启动 Podman machine。
- 修改 LaunchAgent plist 后额外运行 `plutil`，修改 installer 后运行
  `bats platform/macos/tests`。
