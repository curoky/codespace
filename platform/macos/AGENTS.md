# macOS Host

本目录拥有 macOS installer、package manifest、rootfs 和 Host helper。

- `install.sh` 是唯一入口，必须从自身位置解析仓库并幂等更新明确列出的 target。
- `rootfs/Users/x/` 按 macOS 绝对路径保存 Host-owned home 配置；同内容的多个
  target 使用相对 symlink，不建立副本。
- Workspace-owned home 配置直接链接 Workspace rootfs source，不复制到本目录。
- 需要独立权限或会被覆盖的文件使用 copy，其余配置使用 symlink。
- 默认只加载 Atuin daemon；Atuin server 必须显式启用。
- Podman 与 Colima 启动命令相互独立，installer 不替用户选择 runtime。
- LaunchAgent 不保存真实 credential。

修改 installer 或 LaunchAgent 后运行根目录 `task check` 并校验 plist。
