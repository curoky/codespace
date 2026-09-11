# Workspace Image

本目录构建 control plane 唯一支持的 Workspace runtime。构建、启动和 Agent
contract 见 [`DESIGN.md`](DESIGN.md)。

## 约束

- 控制面只挂载一个 editor cache root，不得感知或单独挂载具体 IDE 路径。
- `rootfs/` 拥有 Workspace SSH authorized key 与 host key；Host client bundle
  必须与这两项 trust material 保持一致。
- `workspace-init` 只负责 Workspace 数据；`home-init` 只负责用户与 editor state。
- 服务依赖必须表达在 s6 graph 中，不在 runtime helper 内轮询其他服务。
- Agent 只监听 control UDS；外层目录保持私有并只经 SSH forwarding 访问。
- 无认证的本地服务只监听容器 loopback。
- encryption 只作用于 Workspace 数据；必须显式启用且缺少 key 时 fail-fast，
  不降级为明文。

mount、s6 dependency、Agent protocol 或 managed runtime input 变化时，同步控制面
调用方与行为测试；s6 bootstrap 变化还需验证 Service image。
