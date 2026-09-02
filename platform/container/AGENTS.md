# Container Platform

`platform/container/` 拥有所有 OCI image source。构建 context 固定为仓库根；
image family、tag、版本和 build matrix 以 build script、Dockerfile 与 workflow 为准。

## 边界

- 每个 leaf 拥有自身 Dockerfile、rootfs 和 runtime helper；rootfs 路径映射容器内
  绝对路径。
- s6 skeleton 与安装器由 Workspace 持有。Service 只复制这两项 bootstrap，再叠加
  自身 rootfs；s6 service definition 仍由各 leaf 拥有。
- runtime helper 只做单一职责并保持 executable；secret 文件不得向无关用户开放。
- 每个 leaf 只有一个本地构建入口，必须解析仓库根、校验参数并传播构建失败。
- 不提交生成的 venv、cache、database 或 image artifact，也不发布兼容 tag。

修改 Workspace s6 bootstrap 时必须检查所有 Service 消费方。
