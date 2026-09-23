# macOS Platform

- `rootfs/Users/x/` 按 home 相对路径保存 source；共享配置使用相对 symlink，需要独立权限
  或运行期修改的文件才 copy。
- `Brewfile` 是完整 Homebrew 状态；`brew bundle --force-cleanup` 会删除 manifest 外依赖。
- 可选 daemon 必须显式启用；installer 不负责启动 Podman machine。
- 修改 LaunchAgent plist 后额外运行 `plutil`，修改 installer 后运行
  `bats platform/macos/tests`。
