# macOS Platform

- `rootfs/Users/x/` 按 macOS home 相对路径保存 source；相同内容使用相对 symlink，
  不维护额外 source-to-target 映射。
- 需要独立权限或运行期修改的文件使用 copy，其余 home 配置使用 symlink。
- Brewfile 是完整 Homebrew 状态，`brew bundle --force-cleanup` 会移除 manifest 外依赖。
- 可选 daemon 必须显式启用；installer 不负责启动 Podman machine。
- LaunchAgent plist 变化必须额外做 `plutil` 语法校验。
