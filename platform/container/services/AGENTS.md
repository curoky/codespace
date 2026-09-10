# Service Images

每个直接子目录拥有一个 Host 单例 Service image 及其独立验证入口。

- Service 不包含 Workspace mount、SSH、deploy key、provider token 或控制面逻辑。
- bridge 内的 server 监听容器接口；Host port 必须显式选择 bind address。
  local-only 使用 loopback，跨容器访问使用 bridge gateway，不得默认 wildcard。
- Service 只复用 Workspace 的 s6 bootstrap，自身拥有 service definition。
- `support` 是唯一允许访问 Host rootful Podman socket 的 Service，能力必须限制在
  image maintenance。
- vLLM 与 SGLang 竞争同一组 GPU 和 API endpoint，不得同时部署；控制面不负责
  仲裁。
- smoke script 必须复现生产容器契约，不形成第二套配置模型。

修改公共约束时检查所有 Service leaf、smoke script 与控制面示例配置。
