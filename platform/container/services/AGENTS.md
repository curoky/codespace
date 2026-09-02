# Service Images

每个直接子目录拥有一个 Host 单例 Service 的 Dockerfile、rootfs、构建与 smoke
入口。identity、label、tag 和参数以控制面 model 与各 leaf 代码为准。

- Service 独立于 Project/Workspace，不包含 Workspace mount、SSH、deploy key、
  provider token 或控制面。
- 网络服务默认只绑定 Host loopback。
- Service 仅从 Workspace 复用 s6 bootstrap，自身拥有完整的 service definition。
- `support` 是唯一允许访问 Host rootful Podman socket 的 Service，能力必须限制在
  image maintenance。
- vLLM 与 SGLang 竞争同一 GPU 与默认端口，同一 Host 只能运行一个。
- smoke script 验证生产容器契约，不形成第二套生命周期。

公共边界变化时同步检查所有 Service leaf 和控制面配置。
