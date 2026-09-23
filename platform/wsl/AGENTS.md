# WSL Platform

- Windows-only keep-alive 与网络配置属于 `windows/`，不进入 Linux rootfs。
- WSL 继承 Workspace filesystem，但 `wsl` s6 bundle 不启动 `podman` service。
- 修改 Workspace s6 dependency 或 WSL boot wiring 后，验证 build、export、Windows
  import、boot 与 SSH。
