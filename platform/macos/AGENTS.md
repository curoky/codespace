# macOS Host

本目录拥有 macOS home 配置、installer 与独立的 Host 资产。

- `install.sh` 是 home 配置的唯一安装入口；当前只安装受管文件并生成 shell
  integration，必须从自身位置解析仓库且保持幂等。
- `rootfs/Users/x/` 按 macOS 绝对路径保存 Host-owned home 配置；同内容的多个
  target 使用相对 symlink，不建立副本。
- Workspace-owned home 配置直接链接 Workspace rootfs source，不复制到本目录。
- 需要独立权限或会被覆盖的文件使用 copy，其余配置使用 symlink。
- package bootstrap、默认应用、LaunchAgent 与 container runtime helper 不属于当前
  installer 流程；Podman 与 Colima helper 保持独立。
- LaunchAgent 不保存真实 credential。

修改 installer 或 LaunchAgent 后运行根目录 `task check` 并校验 plist。
