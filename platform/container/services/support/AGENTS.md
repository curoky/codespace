# Support Service

本目录把 Atuin server 与 image maintenance 放在一个 Host 单例 Service 中。

- Atuin 使用外部数据库，credential 只通过 Podman secret 注入。
- 本 Service 是访问 Host rootful Podman socket 的唯一例外；维护脚本只能拉取固定
  image 清单并清理 dangling image。
- 网络模式差异、调度和维护目标以 Dockerfile、rootfs 与 smoke script 为准。
- 不在 smoke script 中引入独立配置或生产状态。
