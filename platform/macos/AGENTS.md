# macOS Host

本目录拥有 macOS home 配置、installer、package manifest 与 Host helper。

- `install.sh` 必须从自身位置解析仓库并保持幂等；当前执行面只包括
  受管 home 配置和 shell integration。
- `rootfs/Users/x/` 按 macOS 绝对路径保存 Host-owned home 配置；同内容的多个
  target 使用相对 symlink，不建立副本。
- Workspace-owned home 配置直接链接 Workspace rootfs source，不复制到本目录。
- secret、SSH config 等需要独立权限的文件使用 copy，其余配置使用 symlink。
- package bootstrap、默认应用与 LaunchAgent 尚未接入 installer；不要把未调用 helper
  当作已部署行为。
- Podman 与 Colima 启动 helper 相互独立，installer 不选择 container runtime。
- LaunchAgent 不保存真实 credential。

修改 installer、home source 或 LaunchAgent 后运行根目录 `task check`；plist 变化另做
语法校验。
