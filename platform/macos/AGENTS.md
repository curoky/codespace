# macOS Host

本目录拥有 control plane 唯一支持的 client 环境：`x` 用户的 macOS home 配置、
installer、package manifest 与 Host helper。

- `install.sh` 必须幂等，只管理仓库声明的状态，不删除未受管应用或配置。
- `rootfs/Users/x/` 按 macOS 绝对路径保存 Host-owned home 配置；同内容的多个
  target 使用相对 symlink，不建立副本。
- installer 按相对 home path 安装文件；source 与 `$HOME` target 布局必须一致，
  不维护 source-to-target 映射。
- Workspace-owned home 配置在本 rootfs 的对应路径使用相对 symlink 指向 Workspace
  rootfs source，不建立副本；installer 仍只消费本 rootfs。
- Workspace SSH client bundle 属于 macOS Host；需要独立权限的配置使用 copy，
  其余 home 配置使用 symlink。
- Brewfile 只管理声明的软件；installer 不卸载 manifest 外的应用。
- 可选 daemon 必须显式启用；installer 不负责启动 Podman machine。

修改 installer、home source 或 LaunchAgent 后运行 `task check`；plist 变化另做语法
校验。
