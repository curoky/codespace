# Platform

`platform/` 拥有 OCI image、Host installer 和 WSL 资产，不包含 control plane
业务代码。具体版本、tag、构建参数和文件清单以 Dockerfile、manifest 与脚本为准。

## 边界

- 镜像与运行资产使用 `codespace` 命名，并放在 `/opt/codespace/`。
- Workspace home 配置只在 `container/workspace/rootfs/home/x/` 维护；macOS
  installer 可直接链接选定配置，但不得在 `dotfiles/` 建立副本。
- s6 bootstrap 由 Workspace 持有；Service 只能复用声明的 bootstrap 入口。
- leaf build/smoke/export 脚本必须从自身位置解析仓库根并对参数 fail-fast。
- Linux/macOS installer 必须幂等；WSL rootfs 不承担 Windows Host 配置。

跨平台约束变化时同步检查消费者的 Dockerfile、installer 和 leaf 文档。
