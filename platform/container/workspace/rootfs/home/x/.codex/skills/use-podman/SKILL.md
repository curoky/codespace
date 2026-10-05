---
name: use-podman
description: >-
  使用本机 rootless Podman 或 Buildah 构建、运行和排查 container；当任务涉及 podman build、
  podman run、Containerfile、Dockerfile、image 或本地容器运行时调用。
---

# Use Podman

- 直接使用 `podman build` 和 `podman run`。
- 只操作当前用户的 rootless runtime。它固定连接
  `unix:///run/user/5230/podman/podman.sock`，state 位于 `/opt/podman/data`；不要尝试连接其他
  Podman socket。
- 内部 container 禁用 cgroups，不要依赖 cgroup resource limit。
- rootless build 因外部 cgroup 环境失败时，运行：

  ```bash
  buildah bud --isolation=chroot <build-context>
  ```
