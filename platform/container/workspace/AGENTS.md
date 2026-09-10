# Workspace Image

本目录构建可独立运行或由 control plane 管理的开发 Workspace。构建与启动模型
见 [`DESIGN.md`](DESIGN.md)。

## 边界

- `rootfs/home/x/` 是 Workspace-owned home 配置的唯一 source；Host 可直接链接
  选定文件，不得建立副本。
- Service 只能复用本目录公开的 s6 skeleton 与安装器。
- 运行资产放在 `/opt/codespace/`，image 不包含仓库 checkout 或 Host 固定路径。
- `workspace-init` 只负责 Workspace 数据；`home-init` 只负责用户与 editor state。
- sshd、WebDAV 与 Agent 的依赖必须表达在 s6 graph 中，不在脚本内轮询彼此。

## 安全

- deploy private key 只在 Workspace 内生成；Agent 只返回 public key。
- provider 与 Workspace SSH host key verification 不得关闭。
- Agent 只监听 control UDS；外层目录保持私有并只经 SSH forwarding 访问。
- Atuin server 由 Workspace 持有，默认只监听容器 loopback；外部数据库 credential
  只通过 root-only secret 注入。
- WebDAV 无认证且默认只监听容器 loopback；非 loopback 暴露必须由部署方显式
  限制。
- encryption 只作用于 Workspace 数据；必须显式启用且缺少 key 时 fail-fast，
  不降级为明文。

mount、s6 dependency、Agent protocol 或 managed runtime input 变化时，必须同步控制面
调用方与行为测试。
