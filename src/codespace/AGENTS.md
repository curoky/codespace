# Codespace Control Plane

`src/codespace/` 拥有 localhost-only、single-process control plane。架构与生命周期
见 [`DESIGN.md`](DESIGN.md)。

## 模块边界

- 依赖方向为 `web -> control -> workspaces/services -> runtime`；
  `resources.py` 拥有跨领域身份、名称约束与业务错误，`runtime/` 不依赖 Config 或 Web。
- Service 与 Workspace 共用 ControlPlane 和 OperationStore；领域模块只承载 metadata、
  inventory 与 Workspace bootstrap，不各自实现排队、日志或隧道管理入口。
- HTTP 输入与 Agent 响应由 Pydantic 校验；Dashboard 直接投影已验证的领域数据。
  Agent HTTP-over-UDS 使用 HTTPX，必须保持有界读取与异常路径的连接释放。
- YAML 只在入口读取；Pydantic model 是运行期唯一配置来源。
- container 覆盖层只由 Config 合并；runtime Spec 的集合不可为 `None`，network 必须确定。
- Config 表达 desired placement；deployed metadata 只读 labels，状态只读 Podman。
- 固定 filesystem、用户 home 与进程布局归 platform；控制面只传 placement 和实例输入。
- Workspace 的 network mode 固定为 bridge；只有 Service 可在配置中选择网络模式。
- 缺失或冲突的容器 metadata 必须失败，不从 Config、mount 或 environment 补齐。
- lifecycle failure 保留现场和 failed operation，不做隐式回滚。
- 维护命令先形成完整计划并隔离单目标失败；只有显式 apply 才修改远端状态。

## 安全边界

- Rootful Podman socket 视为 Host root 权限，SSH host key verification 不得关闭。
- Workspace SSH client contract 由 platform 预置；控制面只维护每个 Workspace 的
  `~/.ssh/codespace/workspaces/` route 文件。
- provider token 只存在于配置和进程内存；deploy private key 只存在于 Workspace。
- Project 配置不得覆盖控制面保留的 runtime input。

schema、生命周期、transport 或安全边界变化时补充聚焦测试，并运行 `task check`。
