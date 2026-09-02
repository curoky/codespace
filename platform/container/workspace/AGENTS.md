# Workspace Image

本目录构建可独立运行、也可由 control plane 管理的开发 Workspace。生命周期见
[`DESIGN.md`](DESIGN.md)。

## 边界

- `rootfs/home/x/` 是 Workspace-owned home 配置的唯一 source；macOS 可直接链接
  选定文件，但不得复制到 `dotfiles/`。
- Service 只能复用本目录的 s6 skeleton 与安装器，不能依赖其他 Workspace 实现。
- 运行资产放在 `/opt/codespace/`，image 不包含仓库 checkout 或 Host 固定路径。
- `bin`、`extensions` 持久 mount 遮蔽的 editor 扩展先作为 immutable template
  烤入 image，再由 init helper 幂等播种；其余 home 配置直接放入 rootfs。

## 安全

- deploy private key 只在 Workspace 内生成；Agent 只返回 public key。
- provider host key verification 不得关闭；sshd 默认只绑定 loopback。
- Agent 只监听 control UDS；外层目录保持私有并只经 SSH forwarding 访问。
- encryption 只作用于 Workspace 数据，upload 与 cache 保持明文。

mount、s6 dependency 或 Agent protocol 变化时，必须同步控制面调用方与行为测试。
