# WSL Platform

- Windows-only keep-alive 与网络配置只放在 `windows/`，不进入 Linux rootfs。
- 修改 Workspace s6 dependency 或 WSL boot 后，验证 export、import、boot 与 SSH。
- WSL 会继承 Workspace 的 Podman binary、配置和 `/opt/podman/data`，但 `wsl` bundle
  不启动 `podman` service；rootless Podman 当前只属于 OCI Workspace runtime contract。
