# WSL Platform

本目录在 Workspace image 上叠加 WSL rootfs，并导出可直接导入的压平 artifact。
流程见 [`DESIGN.md`](DESIGN.md)。

- WSL 的 PID 1 是 Microsoft `/init`；不引入 systemd 或第二套 init。
- `docker export` 会丢弃 OCI metadata，因此运行所需 wiring 必须存在于 rootfs。
- boot helper 启动独立 s6 bundle；该 bundle 不包含 Workspace Agent。
- Windows keep-alive 与 Host 配置只放在 `windows/`，不写入 Linux rootfs。
- 网络暴露由 Windows 管理，不在 WSL rootfs 中增加另一套转发服务。

base image、tag、bundle、artifact 名称和命令以 Dockerfile、rootfs、build/export
脚本及 workflow 为准；改变启动或导出语义时同步更新 `DESIGN.md`。
