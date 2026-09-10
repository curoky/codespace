# Support Service

本目录把 Atuin server 与 image maintenance 放在一个 Host 单例 Service 中。

- Atuin 使用外部数据库，credential 只通过 Podman secret 注入。
- 本 Service 是访问 Host rootful Podman socket 的唯一例外；维护脚本只能拉取固定
  image 清单并清理 dangling image。
- 使用 Podman 默认 bridge，不管理网络。Linux 向其他容器提供的端口显式发布到
  Host bridge 网关，macOS 本机访问使用 loopback 发布。
- 外部数据库的地址族必须能由 Host 的既有容器网络访问。
- 不在 smoke script 中引入独立配置或生产状态。
