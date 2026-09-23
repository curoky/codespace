# Control Plane

- `resources.py` 拥有跨领域 identity、名称约束与业务错误。
- `config.py` 只解析 immutable desired state；已部署资源从 Podman labels 与 inspect
  还原，不使用当前配置补齐。
- 依赖方向是 `web -> control -> workspaces/services -> runtime`；`runtime/` 只提供
  SSH、Podman 和 Host filesystem primitive，不读取配置。
- `maintenance/` 命令必须先生成完整计划，只有显式 `--apply` 才修改远端状态。
