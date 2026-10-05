---
name: manage-services
description: >-
  管理和排查由 s6 supervision 管理的后台服务；当任务涉及服务状态、日志、启动、停止、重启，
  或某个 daemon 不工作时调用。
---

# Manage Services

- 使用 s6 管理后台服务，不要调用 `systemctl`。
- 查看状态：`s6-svstat /run/service/<service>`。
- 查看日志：`tail /var/log/s6.<service>.log`。
- 启动或停止 longrun service：`s6-svc -u /run/service/<service>` 或
  `s6-svc -d /run/service/<service>`。
- 重启 longrun service：`s6-svc -r /run/service/<service>`。
