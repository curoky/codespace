# Container Platform

本目录拥有 OCI image source；所有构建都以仓库根为 context。

## 边界

- 每个 image leaf 拥有自己的 Dockerfile、构建入口、rootfs 和 runtime helper；
  rootfs 路径映射容器内绝对路径。
- s6 skeleton 与安装器由 Workspace 持有。Service 只复制这两项 bootstrap，再叠加
  自身 rootfs；s6 service definition 仍由各 leaf 拥有。
- s6 service 的文件日志统一使用 `/var/log/s6.*.log` 命名，供控制面按前缀发现。
- runtime helper 保持单一职责与 executable；secret 文件不得向无关用户开放。
- 每个 leaf 只有一个本地构建入口，参数错误和构建失败必须原样失败。
- 不提交生成的 venv、cache、database 或 image artifact，也不发布兼容 tag。

Workspace s6 bootstrap 的变化必须在所有 Service image 上验证。
