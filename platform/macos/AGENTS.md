# macOS Host

本目录拥有 macOS home 配置、installer、package manifest 与 Host helper。
这是 `src/codespace` control plane 唯一支持的 client 环境，用户与 home 固定为
`x`、`/Users/x`。

- `install.sh` 必须从自身位置解析仓库并保持幂等；执行面包括 Homebrew/Brewfile、
  binman、受管 home 配置、shell integration、默认应用和 Atuin daemon。
- `rootfs/Users/x/` 按 macOS 绝对路径保存 Host-owned home 配置；同内容的多个
  target 使用相对 symlink，不建立副本。
- installer 按相对 home path 安装 Host-owned 文件；source 与 `$HOME` target 的
  目录布局必须一致，不维护 source-to-target 映射。
- Workspace-owned home 配置在本 rootfs 的对应路径使用相对 symlink 指向 Workspace
  rootfs source，不建立副本；installer 仍只消费本 rootfs。
- Workspace SSH client bundle 属于 macOS Host，完整存放在
  `rootfs/Users/x/.ssh/codespace/`。
- secret、SSH config 等需要独立权限的文件使用 copy，其余配置使用 symlink。
- Starship 与 Atuin shell integration 直接使用 binman store 中的 package 资产。
- Brewfile 只管理声明的软件；installer 不卸载 manifest 外的应用。
- Atuin server 只通过 `--with-atuin-server` 显式启用；LaunchAgent 资产按相同 home
  相对路径存放在 `rootfs/Users/x/Library/LaunchAgents/`。
- 本地 container runtime 固定为 rootful Podman；installer 不负责启动 machine。

修改 installer、home source 或 LaunchAgent 后运行根目录 `task check`；plist 变化另做
语法校验。
