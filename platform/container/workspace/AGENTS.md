# Workspace Image

提供可独立启动的交互式开发环境。主 image 拥有基础 runtime、rootfs 与 s6 graph；只读
resource payload 提供可选工具。实例配置由控制面决定。

## Documentation

AGENTS.md 保留核心诉求、职责边界、跨文件不变量、外部兼容约束和必要验证入口。尚未解决或
仍依赖规避措施的常见问题，记录触发条件、影响和处理方式，确认限制消除后再删除。
已有测试不代表约束的原因可以省略；工具清单、版本、完整布局、CLI 参数与执行流程以
Dockerfile、manifest、脚本、类型和测试为准，不在文档中复述。

- 内嵌 Agent：`agent/AGENTS.md`。
- CLI installer：`tools/java-tool/AGENTS.md`、`tools/node-tool/AGENTS.md`。
- 容器内 AI 使用规则：`rootfs/home/x/.codex/AGENTS.md` 与
  `rootfs/home/x/.trae/user_rules/container-environment.md` 保持正文一致；专项操作位于
  `rootfs/home/x/.codex/skills/`。使用约定变化时同步更新对应规则或 skill。

## Contracts

- 主 image 的基础 runtime 与默认 service 不依赖 resource；未挂载 payload 时允许可选工具
  链接悬空。构建期完成 immutable 内容和 s6 graph，启动时不重建。
- 停用的 s6 service definition 保存在 `rootfs/etc/s6/archive/`，不参与服务图编译；重新启用
  时移回 `s6-rc.d`、按需加入 bundle 并重建 image。
- image 拥有的系统内容与用户可写的软件、缓存分离；root service 只使用 root-owned 命令
  路径。用户以 `x` 运行，挂载数据的身份必须与 Host 一致。
- `/workspace`、`/workspace.enc` 与 `/opt/podman/data` 的初始化只准备挂载根，不递归
  chown、迁移或清除已有数据。`home-init` 当前会递归调整指定 IDE 目录的归属，不得把这个
  范围扩大到 Workspace 或 Podman 数据。
- Shell 遵循发行版原生启动规则；应用环境集中在 `rootfs/etc/profile.d/app.sh`，重复加载不
  改变已有 PATH 优先级。开发环境通过 filesystem 提供，不依赖主运行 stage 的 OCI ENV；
  非登录 Bash 继承环境或显式加载 profile。项目覆盖在加载后进行，不用 wrapper 或
  `BASH_ENV` 改写启动规则。
- 默认 Node.js runtime、内置 Node CLI 的 runtime binding 与 editor npm 路径保持一致；
  修改默认版本时同步调整 profile、构建调用与 editor config。
- 依赖 `/workspace` 的 service 必须依赖 `gocryptfs-workspace`；必要 credential 从 runtime
  secret 读取，缺失时 fail-fast。添加依赖不得隐式启用可选 service；启动时的用户安装
  job 不属于 image build，编码后的 payload 不构成 secret 或信任边界。
- service 默认监听 container loopback；对外暴露由控制面配置决定。
- 每个 image 拥有自身的 package metadata，避免跨 package manager 重复安装。binman 的
  launcher、store 与 profile 是完整载荷，必须一起保留；调用方使用稳定入口，不硬编码
  内部 content-addressed store 路径。
- Conda channel 的 ToS 接受记录由 rootfs 的系统级 metadata 提供，供 root 与 `x` 共同
  使用。记录只接受指定版本的条款；条款更新后需重新接受并同步 rootfs，不自动接受新版本。
- 内置 Podman 仅服务 Workspace 用户，不连接 Host Podman。持久数据不能由多个运行中的
  Workspace 共享；已有 storage driver 不自动迁移、重建或删除。
- 保留 rootless Podman 所需的 subordinate IDs、setuid helper、容器权限与 unlimited pids；
  内部 container 禁用 cgroups，shell 与 service 的构建都使用 chroot isolation。GPU CDI
  根据注入的设备和 driver 在运行期生成，image 不携带 Host driver。

## Known Pitfalls

- 系统认证依赖发行版的 setuid `su` 与静态 sudo 可校验的 SHA-512 password hash；替换
  standalone package 或调整密码初始化时，不能丢失这两个兼容条件。
- 归档的 Ollama service 未预装 executable；恢复并启用前需先安装到 service script 指定路径。

## Validation

通用检查遵循根 `AGENTS.md`。行为或 artifact 变更还需构建受影响的 image：

```bash
platform/container/workspace/build.sh
platform/container/workspace/build.sh --resource
```

主 image 与 payload 的接口同时变化时两者都构建。共享 s6 资产变化时，按根文档索引追加
Service 与 WSL 验证；其他被 WSL 继承的 filesystem 变化也需验证 WSL。
