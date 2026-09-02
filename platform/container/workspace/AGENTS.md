# Workspace Image

本目录构建可独立运行、也可由 control plane 管理的开发 Workspace。生命周期见
[`DESIGN.md`](DESIGN.md)；镜像内容以 Dockerfile、rootfs、config 和 scripts 为准。

## 边界

- `rootfs/home/x/` 是 Workspace-owned home 配置的唯一 source；macOS 可直接链接
  选定文件，但不得复制到 `dotfiles/`。
- Service 只能复用本目录的 s6 skeleton 与安装器，不能依赖其他 Workspace 实现。
- 运行资产放在 `/opt/codespace/`，image 不包含仓库 checkout 或 Host 固定路径。
- 被持久 mount 遮蔽的初始配置先作为 immutable template 烤入 image，再由 init
  helper 幂等播种。

## 安全

- deploy private key 只在 Workspace 内生成；Agent 只返回 public key。
- provider host key verification 不得关闭；sshd 默认只绑定 loopback。
- Agent 只监听 control UDS；外层目录保持私有并只经 SSH forwarding 访问。
- encryption 只作用于 Workspace 数据，upload 与 cache 保持明文。

环境变量、mount、s6 dependency 或 Agent 协议变化时，同步控制面调用方、
[`DESIGN.md`](DESIGN.md) 和行为测试。
