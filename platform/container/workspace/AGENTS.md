# Workspace Image

## Scope

主 image 提供可独立启动的交互式环境、基础 runtime、rootfs 与 s6 graph；只读 Resource
payload 提供可选工具，实例配置由控制面拥有。

内嵌 Agent 与 CLI installer 的合同见各自下层 `AGENTS.md`。容器 AI 规则位于
`rootfs/home/x/.codex/AGENTS.md`，与 `.trae/user_rules/container-environment.md` 正文一致；
专项操作位于 `.codex/skills/`，使用约定变化同步对应规则。

## Contracts

- Agent、node-tool、java-tool 是独立 Go executable，共用本目录 module。构建期编译，
  运行期不安装依赖或编译。installer 直接位于用户 Node/Java 根，与 runtime/tools 并列；
  默认 binding 与 profile 一致，构建 stage 显式设置固定用户 HOME。
- macOS arm64 helper 由 `publish-workspace-tools.yaml` 原生构建并经 GHCR/ORAS 分发；
  不含 runtime、package manager 或 Shell。首次安装需已有发布产物；Linux image 从源码
  构建，不依赖 GHCR helper tag。
  ORAS setup Action 使用内嵌 release 列表，升级 CLI 时需同时核对 Action 对目标版本和平台的支持。
- 基础 runtime 和默认 service 不依赖 Resource；无 payload 时允许可选工具链接悬空。
  immutable 内容和 s6 graph 在构建期完成，启动时不重建。停用 definition 位于
  `rootfs/etc/s6/archive/`，恢复时移回服务图、按需加入 bundle 并重建。
- root service 只使用 root-owned 命令路径，用户软件/cache 与系统内容分离。用户以 `x`
  运行，挂载身份与 Host 一致；s6 用户服务显式设置 HOME。
- Workspace、加密数据与 Podman 挂载根只做初始化，不递归 chown、迁移或清理已有数据。
  home-init 的递归归属调整仅限声明的 IDE 目录，不扩大到业务或 Podman 数据。
- Shell 保持发行版原生启动规则，环境集中在 `rootfs/etc/profile.d/app.sh`；重复加载
  不改变 PATH 优先级，首次加载受管工具优先。非登录 Bash 继承环境或显式加载 profile，
  不增加 wrapper、BASH_ENV 或依赖主 runtime stage 的 OCI ENV。
- GCC 由 Nix、LLVM SDK 由 Resource 提供，不改变 Framework/CUDA 的独立兼容组合。
  Go/LLVM 精确版本目录使用 minor/major 相对链接，升级 patch 不改变调用方入口。
- 默认 Node runtime、installer binding、内置 CLI binding 与 editor npm 路径同时更新。
  可移植 Node/Python CLI 与 macOS 对齐，Linux-only CLI 独立声明。
- uv 管理 Python runtime 和隔离 CLI，主 image CLI 绑定默认 interpreter，Resource
  TensorBoard 保留独立 binding。Resource Python 在固定 mount path 安装完整 payload，
  主 image 只链接 runtime 供 uv discovery，不移动 virtualenv 或改写 interpreter binding。
- rustup/SDK 根独立于用户 CARGO_HOME；运行期 `~/.cargo` 保留用户 CLI 与 cache。
  archive 精确锁定并校验，Rust SDK 不使用浮动 channel。
- 依赖 `/workspace` 的 service 必须依赖 gocryptfs-workspace；credential 从 runtime secret
  读取，缺失时失败。添加依赖不隐式启用可选服务；用户启动安装 job 不属于 image build，
  编码 payload 不是 secret 或信任边界。service 默认监听 loopback。
- 每个 image 保有自身 package metadata，不跨 manager 重复安装。binman launcher/store/
  profile 是完整 payload，调用稳定入口，不硬编码 content-addressed store 内部路径。
- Conda ToS 使用 rootfs 系统 metadata 供 root/x 共用，只接受声明版本；条款更新后显式
  重新接受并同步 rootfs，不自动接受未来条款。
- 内置 rootless Podman 仅服务 Workspace 用户，不连接 Host；运行实例不共享持久 storage，
  不自动迁移 driver。保留 subordinate IDs、setuid helper、必要权限与 unlimited pids；
  内部禁用 cgroups，构建使用 chroot isolation。GPU CDI 在运行期按注入设备/driver 生成。

## Pitfalls

- 官方 Linux LLVM archive 不含 sysroot；Clang 项目须显式配置 Nix GCC 的系统 headers、
  启动对象及 runtime/linker。仅 `--gcc-install-dir` 或 `clang --version` 不足以证明可用，
  不通过 wrapper 或重复安装系统 compiler 隐藏此约束。
- 系统认证需要发行版 setuid su 与静态 sudo 可校验的 SHA-512 password hash；替换
  standalone package 或密码初始化不能丢失这两个条件。
- 归档 Ollama service 未预装 executable，恢复前先安装到其脚本指定路径。

## Validation

通用 CI 使用 uv-managed Python；Resource discovery 测试从其真实 runtime 构造链接，不借用
Homebrew 或系统 Python 的安装布局。

本地构建默认发行版最终主 image，验证无 Resource 也能启动：

```bash
/opt/podman/bin/podman build . --network=host \
  --file platform/container/workspace/Dockerfile \
  --target workspace --tag localhost/codespace-workspace-test --pull=missing
```

Resource 在仓库外临时配方中裁剪无关工具，保留受影响工具的真实安装、payload、binding、
权限与测试；接口变化同时验证主 image 的挂载、链接和调用，交付说明裁剪范围。
完整 Resource 与发行版矩阵由 CI 构建。继承的 filesystem/s6 变化按根索引追加 Service/WSL 验证。
