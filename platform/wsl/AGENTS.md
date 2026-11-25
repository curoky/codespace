# WSL Platform

## Scope

将 Workspace filesystem 派生为 WSL 可导入的 flat rootfs。WSL 是本地 distribution，不是
受管 remote Host，不运行 OCI entrypoint；Linux boot overlay 与 Windows-side wiring 分开。

## Contracts

- [Dockerfile](Dockerfile) 继承指定 Workspace image，叠加本目录 rootfs，并在构建时
  重新编译 s6 graph；WSL-specific 修正留在 overlay，不给共享 source 添加 platform branch。
- flat export 只有 filesystem，OCI entrypoint、environment、labels、volume 和 healthcheck
  均不保留，不能用 image 启动成功证明 WSL boot 可用。
- [wsl.conf](rootfs/etc/wsl.conf) 指定用户 `x` 和 boot helper；Microsoft `/init` 保持 PID 1，
  helper 直接启动 inherited s6 graph 的 `wsl` bundle。该 bundle 不启用 rootless Podman，
  不假设控制面注入 Workspace secret、mount 或 environment。
- [windows](windows/) 只拥有 keep-alive 和 `.wslconfig` sample；PowerShell task 与 Windows
  network/runtime policy 不进入 Linux rootfs，build/export 不自动修改 Windows 状态。

## Main Flows

[build.sh](build.sh) 装配 overlay image，[export.sh](export.sh) 创建临时 container，
用 filesystem export 和 gzip 输出 rootfs；Windows 显式安装/导入后，`/init` 调用
[boot.sh](rootfs/opt/codespace/wsl/boot.sh)，等待 s6 readiness 再启动 `wsl` bundle。

## Runtime I/O

- **Reads**：build 读取仓库 root context、Dockerfile 与 overlay；export 读取指定 image
  filesystem。所需 base/registry 由 Dockerfile 和 image 参数确定，不上传用户业务文件。
- **Writes**：build 写本地 image；export 直接覆盖指定输出文件，默认是当前目录的
  `codespace.wsl`。退出时尝试移除临时 container；失败可能保留部分 gzip 输出，不恢复旧文件。
- **Linux Changes**：boot 在 distribution 内以 root 应用声明的 sysctl，写 `/run/s6` 的
  environment、通知管道与 service state，再启动 s6；不在 Windows Host 应用 Linux 配置。
- **Windows Changes**：[setup-keepalive.ps1](windows/setup-keepalive.ps1) 是需要 elevated
  PowerShell 的显式操作：创建或替换指定 distribution 的 Scheduled Task，并立即启动，
  以 SYSTEM 发起 root `sleep infinity` 会话。脚本不自动应用 `.wslconfig` sample。
- **Results & Failure**：成功 export 只代表 rootfs 文件已生成，不代表 WSL 已导入或运行。
  keep-alive 注册与启动不是事务，启动失败后 task 可保留，移除需显式 unregister。

## Pitfalls

Workspace filesystem 变化进入下一次 WSL build；service dependency、init、环境或持久路径
变化须检查 `wsl` bundle 是否仍独立可用。仅当 idle-timeout 支持缺失/失效时显式安装
Scheduled Task，不将该操作当作 build/export 的自动补救。

## Validation

构建与导出入口见 build/export scripts；它们使用 Docker-compatible CLI，在容器环境
按根约定使用 `/opt/podman/bin/podman` 执行相应构建/导出。artifact 行为变化还需在 Windows
验证 import、boot、keep-alive 与 SSH 登录，单独构建不能覆盖 flat-rootfs boot 合同。
