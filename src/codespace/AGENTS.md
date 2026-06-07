# Codespace Control Plane

`src/codespace/` 是 localhost-only、single-process control plane。架构与生命周期见
[`DESIGN.md`](DESIGN.md)。

## 边界

- 依赖方向为 `web -> control -> workspaces/services -> runtime`；`runtime/` 不依赖
  Config、manager 或 Web，Workspace 与 Service 不互相调用。
- YAML 只在入口读取；Pydantic model 是运行期唯一配置来源。
- Config 表达 desired placement；已有容器元信息只读 labels，状态只读 Podman。
- 缺失或冲突的容器 metadata 必须失败，不从 Config、mount 或 environment 补齐。
- lifecycle failure 保留现场和 failed operation，不做隐式回滚。
- 维护命令先形成完整计划并隔离单目标失败；只有显式 apply 才修改远端
  状态。

## 安全

- Rootful Podman socket 视为 Host root 权限，SSH host key verification 不得关闭。
- provider token 只存在于配置和进程内存；deploy private key 只存在于 Workspace。
- Agent 只监听 Workspace UDS，并经 OpenSSH StreamLocal forwarding 访问。
- Project 配置不得覆盖控制面保留的 runtime input。
- Web 只监听 loopback，并保持无 Node.js 构建链的原生静态资源。

schema、生命周期、transport 或安全边界变化时必须补充聚焦测试；统一运行
根目录 `task check` 验证。
