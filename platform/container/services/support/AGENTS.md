# Support Service

本目录提供 Host 单例的 image maintenance Service。

- 本 Service 是访问 Host rootful Podman socket 的唯一例外；维护脚本只能拉取固定
  image 清单并清理 dangling image。
- 使用 Podman 默认 bridge，不管理网络、不发布端口、不接收数据库 credential。
- 不在 smoke script 中引入独立配置或生产状态。
