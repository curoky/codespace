# WSL Platform

## Scope

将 Workspace filesystem 派生为 WSL flat rootfs；本地 distribution 不属于受管 Host。
[build.sh](build.sh)/[export.sh](export.sh) 装配并导出 image，Windows 显式导入后由
`/init` 调用 [boot.sh](rootfs/opt/codespace/wsl/boot.sh) 启动 inherited s6 的 `wsl` bundle。

## Contracts

- [Dockerfile](Dockerfile) 构建时重编 s6 graph；WSL-specific 修正留在 overlay，不加共享
  source platform branch。export 不保留 OCI 启动 metadata，不能靠 image 运行证明 WSL boot。
- [wsl.conf](rootfs/etc/wsl.conf) 指定用户 `x`/boot helper，Microsoft `/init` 保持 PID 1；
  bundle 不启 rootless Podman，不假设控制面注入 secret/mount/environment。
- [windows](windows/) policy 不进入 Linux rootfs，build/export 不自动修改 Windows 状态；
  idle-timeout 支持缺失/失效时才显式安装 keep-alive Scheduled Task。

## Runtime I/O

- **Reads**：export 读取指定 image filesystem；image/registry 由参数与 Dockerfile 确定。
- **Writes**：export 直接覆盖输出文件，默认当前目录 `codespace.wsl`；退出尝试移除临时
  container，失败可能保留部分 gzip 文件，不恢复旧输出。
- **Linux Changes**：boot 在 distribution 内以 root 应用 sysctl，写 `/run/s6` environment/
  通知管道/service state，等待 s6 readiness 后启 bundle，不改 Windows Host Linux 配置。
- **Windows Changes**：[keep-alive](windows/setup-keepalive.ps1) 需 elevated PowerShell，
  创建/替换并启动指定 distribution 的 Scheduled Task，以 SYSTEM 发起 root sleep 会话；
  不自动应用 `.wslconfig` sample。
- **Results & Failure**：export 成功不代表已导入/运行；task 注册后启动失败可保留 task，
  移除须显式 unregister，操作无自动回滚。

## Validation

Workspace service/init/环境/持久路径变化检查 bundle 独立性；artifact 变化构建/export 后
在 Windows 验证 import、boot、keep-alive 与 SSH，通用检查或单独 build 不能替代。
