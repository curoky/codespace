# WSL Platform

本目录把 Workspace image 转换为可导入的 WSL distribution。启动与导出模型见
[`DESIGN.md`](DESIGN.md)。

- WSL 的 PID 1 是 Microsoft `/init`；不引入 systemd 或第二套 init。
- export 会丢弃 OCI metadata，运行 wiring 必须完整存在于 rootfs。
- WSL bundle 不启动需要 control plane bootstrap 的 Workspace Agent。
- Windows keep-alive 与 Host 网络配置只放在 `windows/`，不写入 Linux rootfs。
- 网络暴露由 Windows 管理，不在 WSL rootfs 中增加另一套转发服务。

修改 Workspace s6 dependency、WSL 启动或导出语义时，验证 import、boot 与 SSH
可达性。
