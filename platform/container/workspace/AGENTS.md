# Workspace Image

本目录构建 `src/codespace` 唯一支持的远程开发 runtime，只由 control plane 启动，
不提供 standalone 或其他 Workspace image contract 的兼容路径。构建与启动模型见
[`DESIGN.md`](DESIGN.md)。

## 边界

- `rootfs/home/x/` 是 Workspace-owned home 配置的唯一 source；Host 可直接链接
  选定文件，不得建立副本。
- IDE `bin`/`extensions` 在 image home 中固定链接到 `/cache`；控制面不得感知或
  单独挂载具体 IDE 路径。
- shell integration 与 IDE 默认 manifest 在构建期准备；运行期不改写固定路径，
  只初始化尚无 manifest 的持久 IDE cache。
- `rootfs/` 拥有 Workspace SSH authorized key 与 host key；Host client bundle
  必须与这两项 trust material 保持一致。
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
