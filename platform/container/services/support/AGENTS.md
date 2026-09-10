# Support Service

本目录只提供 Host image maintenance。

- 通过 Host rootful Podman socket 只执行固定 image 预热和 dangling image 清理。
- 不管理网络、不发布端口，也不接收 Workspace 或数据库 credential。
- smoke script 只验证部署契约，不持有额外状态。
