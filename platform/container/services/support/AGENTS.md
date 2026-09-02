# Support Service 约束

本目录构建 `ghcr.io/curoky/codespace:service-support`。每个 host 最多运行一个
`codespace-service-support`，单容器同时提供 Atuin server 与 image maintenance。

## Runtime

- s6 的 `default` bundle 启动 `atuin-service` 与 `supercronic` 两个 longrun。
- Atuin 默认监听 `127.0.0.1:8002`，关闭开放注册；`ATUIN_DB_URI` 必须通过 Podman
  secret `atuin_db_uri` 注入，缺失时 smoke 脚本 fail-fast。
- Linux 使用 host network；macOS 使用 bridge network，把
  `127.0.0.1:8002` 映射到容器 `8002`，并设置 `ATUIN_HOST=0.0.0.0`。
- Atuin 使用外部数据库，本 Service 不挂载持久数据目录。

## Image Maintenance

- `supercronic` 按 `rootfs/etc/supercronic/crontab` 调度
  `/opt/codespace/support/{pull,prune}-images.sh`。
- 预热清单写死在 `pull-images.sh`，当前只预热 host 原生平台的
  `ghcr.io/curoky/codespace:workspace-debian13`。
- `prune-images.sh` 调用 Podman REST API 的无 filter `POST /images/prune`，只清理
  dangling image，不得启用 `all`。
- host rootful Podman socket 是本 Service 的唯一特权例外。脚本只能执行上述 pull 与
  prune，不得管理 container、volume、secret 或网络。

## 验证

```bash
platform/container/services/support/build.sh
printf '%s' "$ATUIN_DB_URI" | podman secret create atuin_db_uri -
platform/container/services/support/smoke-linux.sh
platform/container/services/support/smoke-macos.sh
```

smoke 脚本会替换固定名称容器，并写入标准 Service labels；不得在其中引入独立配置或
生产状态。
