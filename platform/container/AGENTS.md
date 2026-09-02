# Container Platform 约束

`platform/container/` 拥有所有 OCI image source。构建 context 固定为仓库根，
Dockerfile 必须使用完整的 `platform/container/...` 或 `dotfiles/...` COPY 路径。

## Image Families

| 路径                    | Tag                                                    |
| ----------------------- | ------------------------------------------------------ |
| `workspace/`            | `ghcr.io/curoky/codespace:workspace-<distro><version>` |
| `services/<name>/`      | `ghcr.io/curoky/codespace:service-<name>`              |
| `frameworks/<project>/` | `ghcr.io/curoky/codespace:framework-<combination>`     |

cache repository 固定为 `ghcr.io/curoky/codespace-cache`。不得发布兼容 alias 或读取
旧 tag。

## Rootfs And s6

- leaf-owned runtime file 放在自身 `rootfs/`，并保持与容器绝对路径相同的目录结构。
- s6 skeleton 与安装器由 Workspace 持有，分别位于
  `workspace/rootfs/etc/s6/skel/` 与 `workspace/scripts/install-s6.sh`。Service
  必须先复制该 skeleton，再复制自身 rootfs，最后调用 Workspace 安装器。
- `install.sh` 依赖 `/opt/bm/profile/s6`，编译 `/etc/s6/db` 并生成
  `/etc/s6/init`；默认 bundle 名为 `default`。
- s6 service definition 由 leaf 拥有。`run`/`up` 只加载环境、设置 uid/fd 并
  `exec` `/opt/codespace/<component>/...`，业务编排留在普通 shell helper。
- service 通过 `s6-envdir -Lf -- /run/s6/container_environment` 读取 OCI
  environment。含 secret 的文件权限不能对无关用户开放。

## Build Scripts

- 每个 leaf 保留单一 `build.sh`，从脚本位置解析 repository root。
- 参数错误返回 exit code `2`；实际 build 失败原样传播。
- 脚本打印最终 image 与 base/combination，不自行 push。
- runtime helper 保持 executable；生成的 venv、cache、database 与 image artifact
  不得进入 Git。

Workspace s6 变更必须至少验证 Workspace 及所有 Service Dockerfile 的 COPY 顺序与
`default` bundle。
