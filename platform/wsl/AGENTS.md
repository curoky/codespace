# WSL Platform

此目录把 Workspace filesystem 派生为可由 WSL 导入的 flat rootfs。WSL 是本地 distribution，
不属于控制面管理的 remote Host，也不运行 OCI entrypoint。

## Artifact Model

- `Dockerfile` 继承指定 Workspace image，叠加 WSL rootfs，并在 build 时重新编译 s6 graph。
- `export.sh` 用临时 container 执行 `docker export | gzip`。导出结果只有 filesystem；OCI
  entrypoint、environment、labels、volume 和 healthcheck 都不会保留。
- `/etc/wsl.conf` 指定用户 `x` 和 boot command。Microsoft `/init` 保持 PID 1，
  `boot.sh` 直接启动 inherited s6 graph 的 `wsl` bundle。
- `wsl` bundle 只启用 WSL 需要的 inherited service，不启动 rootless Podman，也不假设控制面
  注入 Workspace secret、mount 或 environment。
- `windows/` 只拥有 Windows-side keep-alive 和 `.wslconfig` sample；PowerShell task、Windows
  network/runtime policy 不进入 Linux rootfs。

## Change Boundaries

- Workspace rootfs 变化自动进入下一次 WSL build；Workspace service dependency、init、环境或
  持久路径变化时，必须检查 `wsl` bundle 是否仍可独立启动。
- WSL-specific 修正写入本目录 overlay，不在 shared Workspace source 中加入 platform branch。
- Windows Scheduled Task 是对缺失/失效 idle-timeout 支持的显式安装动作；build/export 不应
  自动修改 Windows 状态。

## Validation

```bash
platform/wsl/build.sh
platform/wsl/export.sh
```

artifact 变化必须继续在 Windows 验证 import、boot、distribution keep-alive 与 SSH 登录；仅
Docker build 成功不足以证明 flat-rootfs boot contract。脚本变化再运行 `task check`。
