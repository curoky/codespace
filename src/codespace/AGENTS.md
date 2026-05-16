# Codespace Control Plane

`src/codespace/` 是 localhost-only 的单进程控制面。架构与生命周期见
[`DESIGN.md`](DESIGN.md)。

## 边界

- 依赖方向为 `web -> control -> workspaces/services -> runtime`；`runtime/` 不依赖
  Config、manager 或 Web，Workspace 与 Service 不互相调用。
- 配置只在入口读取并由 Pydantic 完整校验；解析后的 model 是运行期唯一配置来源。
- identity、label、路径、环境变量、API 与 CLI 不在说明文档中维护副本。
- lifecycle failure 保留现场和 failed operation，不做隐式回滚。
- 维护命令默认 dry-run，只有显式 `--apply` 才修改远端状态。

## 安全

- Rootful Podman socket 视为 Host root 权限，SSH host key verification 不得关闭。
- provider token 只存在于配置和进程内存；deploy private key 只存在于 Workspace。
- Agent 只监听 Workspace UDS，并经 OpenSSH StreamLocal forwarding 访问。
- Project 配置不得覆盖控制面保留的 mount、environment 或 secret。
- Web 只监听 loopback，并保持无 Node.js 构建链的原生静态资源。

公开 schema、生命周期或安全边界变化时必须补充聚焦测试；验证入口统一使用根目录
`task check`。
