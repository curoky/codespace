# Control Plane

- `resources.py` 拥有跨领域 identity、名称约束与业务错误。
- `config.py` 拥有 immutable schema、layer merge、placement 与 desired specification
  resolution；不读取 actual state。
- `workspaces/` 与 `services.py` 拥有领域 metadata；已部署资源必须从 Podman labels
  还原，不使用当前配置补齐。
- `control.py` 只做跨领域编排；`runtime/` 只提供 SSH、Podman 和 Host filesystem
  primitive，不读取配置。
