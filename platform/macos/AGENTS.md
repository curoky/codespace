# macOS Host

本目录拥有 macOS installer、package manifest、LaunchAgent 和 Host helper。

- `install.sh` 是唯一入口，必须从自身位置解析仓库并幂等更新明确列出的 target。
- Workspace-owned home 配置直接链接其 rootfs source；其余 Host 配置来自
  `dotfiles/`，不建立重复 source。
- 默认只加载 Atuin daemon；Atuin server 必须显式启用。
- Podman 与 Colima 启动命令相互独立，installer 不替用户选择 runtime。
- LaunchAgent 不保存真实 credential。

修改 installer 或 LaunchAgent 后运行根目录 `task check` 并校验 plist。
