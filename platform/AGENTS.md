# Platform 约束

`platform/` 拥有所有运行平台与镜像资产，不包含 control plane 业务代码。
Workspace image 专属 home 配置由对应 rootfs 持有，Host 用户配置仍属于
`dotfiles/`。

| 路径         | 职责                                                   |
| ------------ | ------------------------------------------------------ |
| `container/` | Workspace、Service、Framework image 与公共容器基础设施 |
| `linux/`     | Linux host 安装入口                                    |
| `macos/`     | macOS host 安装、包清单、LaunchAgent 与 host 脚本      |
| `wsl/`       | WSL2 rootfs overlay、boot、export 与 Windows 辅助配置  |

## Naming

- OCI repository 固定为 `ghcr.io/curoky/codespace`，cache repository 固定为
  `ghcr.io/curoky/codespace-cache`。
- Workspace tag 使用 `workspace-<flavor>`；Service tag 使用
  `service-<service>`；Framework tag 使用 `framework-<combination>`。
- 产品名与本机发行版名使用 `codespace`。平台目录只使用 `linux`、`macos`、
  `wsl` 与 `container`，不引入 OS 或领域别名。
- 镜像运行资产统一放入 `/opt/codespace/<component>`，不得依赖 repository
  checkout 路径。

## Ownership

- Workspace 专属 home 配置只在 `container/workspace/rootfs/home/x/` 维护，不在
  `dotfiles/` 建立镜像副本。Host 配置与明确复用的配置片段仍从
  `dotfiles/<tool>/` 显式选择。
- s6 bootstrap 由 `container/workspace/` 持有；Service 只复制约定的 skeleton
  与安装器，不能引用其他 Workspace 私有实现。
- 每个 leaf 的 build/smoke/export 脚本必须从自身位置解析仓库根，可从任意当前目录
  执行，并对参数 fail-fast。
- Linux/macOS installer 必须幂等；WSL rootfs 不能承担 Windows host 配置。

修改平台公共命名或目录边界时，同步检查各 leaf `AGENTS.md`、Dockerfile COPY 和
构建脚本。
