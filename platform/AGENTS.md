# Platform

`platform/` 拥有 OCI image、macOS Host 配置和 WSL distribution 资产。

## 约束

- Workspace home 配置只在 `container/workspace/rootfs/home/x/` 维护；Host 可直接
  消费该 source，不建立副本。
- macOS-owned home 配置只在 `macos/rootfs/Users/x/` 维护，并按相同相对路径安装。
- s6 bootstrap 由 Workspace 持有；Service 只能复用声明的 bootstrap 入口。
- Windows-only 配置只放在 `wsl/windows/`，不进入 Linux rootfs。

修改共享 home source 或 s6 bootstrap 时，验证所有直接消费者。
