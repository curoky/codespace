---
name: manage-services
description: 查看、启停或排查容器内由 s6 管理的后台服务。
---

# Manage Services

- 使用 s6 管理后台服务，不要调用 `systemctl`。
- 服务列表：`ls /run/service`。
- 查看状态：`s6-svstat /run/service/<service>`。
- 查看日志：`tail /var/log/s6.<service>.log`。
- 启动或停止 longrun service：`s6-svc -u /run/service/<service>` 或
  `s6-svc -d /run/service/<service>`。
- 重启 longrun service：`s6-svc -r /run/service/<service>`。
