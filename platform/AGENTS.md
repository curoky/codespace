# Platform

`platform/` 拥有 OCI image、macOS Host 配置和 WSL distribution 资产。

## 边界

- 镜像与运行资产使用 `codespace` 命名，并放在 `/opt/codespace/`。
- Workspace home 配置只在 `container/workspace/rootfs/home/x/` 维护；Host 可直接
  消费该 source，不建立副本。
- macOS-owned home 配置只在 `macos/rootfs/Users/x/` 维护。
- s6 bootstrap 由 Workspace 持有；Service 只能复用声明的 bootstrap 入口。
- leaf build/smoke/export 脚本必须从自身位置解析仓库根并对参数 fail-fast。
- macOS installer 必须幂等；Windows-only 配置只放在 WSL 的 `windows/` 下。

修改共享 rootfs、s6 bootstrap 或 home source 时，检查所有直接消费者。
