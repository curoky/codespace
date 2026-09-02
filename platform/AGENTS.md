# Platform

`platform/` 拥有 OCI image、Host installer 和 WSL 资产，不包含 control plane
业务代码。

## 边界

- 镜像与运行资产使用 `codespace` 命名，并放在 `/opt/codespace/`。
- Workspace home 配置只在 `container/workspace/rootfs/home/x/` 维护；macOS
  installer 可直接链接选定配置，但不得在 `dotfiles/` 建立副本。
- s6 bootstrap 由 Workspace 持有；Service 只能复用声明的 bootstrap 入口。
- leaf build/smoke/export 脚本必须从自身位置解析仓库根并对参数 fail-fast。
- Linux/macOS installer 必须幂等；WSL rootfs 不承担 Windows Host 配置。

跨平台约束变化时必须覆盖所有消费该约束的 image 与 Host installer。
