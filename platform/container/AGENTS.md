# Container Platform

本目录拥有 OCI image source，所有构建都以仓库根为 context。

## 约束

- 每个 image leaf 拥有自己的 Dockerfile 与构建入口；需要 runtime 资产时由该 leaf
  持有 rootfs 和 helper，rootfs 路径映射容器内绝对路径。
- s6 skeleton 与安装器由 Workspace 持有；Service 只复用 bootstrap，自身拥有
  service definition。
- s6 service 的文件日志统一使用 `/var/log/s6.*.log` 命名，供控制面按前缀发现。
- runtime helper 必须 executable；secret 文件不得向无关用户开放。
- 不提交生成的 venv、cache、database 或 image artifact。

Workspace s6 bootstrap 的变化必须验证所有 Service image。
