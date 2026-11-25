# Workspace Image

## Scope

主 image 提供不依赖 Resource 即可启动的交互式环境、runtime/rootfs 与静态 s6 graph；
只读 Resource 提供可选工具，实例配置由控制面拥有。[Dockerfile](Dockerfile) 拥有构建
stage 和装配细节，Go executable 共用本目录 module，在构建期编译，运行期不安装依赖。

## Context Index

| 任务 | 先读 |
| --- | --- |
| bootstrap/Git 状态/协议 | [Workspace Agent](agent/AGENTS.md) |
| CLI 安装/binding | [node-tool](tools/node-tool/AGENTS.md)、[java-tool](tools/java-tool/AGENTS.md) |
| OAuth/token helper/模型目录 | [Codex LLMBox](tools/codex-llmbox/AGENTS.md) |
| 分发的 AI 规则 | [Codex template](rootfs/home/x/.codex/AGENTS.md)；环境正文同步 [Trae rule](rootfs/home/x/.trae/user_rules/container-environment.md)，按全局规则用途组织 |

## Contracts

- 基础 runtime/默认 service 不依赖 Resource，缺 payload 时可选链接允许悬空。immutable
  内容与 s6 graph 构建期完成；恢复 [archive](rootfs/etc/s6/archive/) definition 时更新
  bundle 并重建，不在启动时重建 graph。
- 通用 AI rules/skills 随 home rootfs 分发，不在构建或启动时从外部仓库安装。共享 skills
  在 Codex source 维护，Trae 用逐项相对链接。
- Resource Python 在固定 mount path 安装完整 payload；主 image 只链接 runtime 供 uv
  discovery，不移动 virtualenv 或改写 binding。主 image CLI 绑定默认 interpreter，
  Resource TensorBoard 保留独立 binding。
- 构建期调用 Node/Java installer 前显式设置 `HOME=/home/x`，确保安装目录与固定 runtime
  binding 对应运行用户；installer 位于 Node/Java 根，不混入 payload runtime。
- root service 只用 root-owned 命令路径；用户 `x` 的挂载身份与 Host 一致，s6 用户服务
  显式设置 HOME。用户软件/cache 与系统内容分离。
- Workspace、加密数据与 Podman 挂载根只初始化，不递归 chown、迁移或清理已有数据；
  home-init 的递归归属调整仅限声明的 IDE 目录。
- Shell 保持原生启动规则，环境集中于 [app.sh](rootfs/etc/profile.d/app.sh)；首次加载
  受管工具优先，重复加载不改变 PATH 优先级。非登录 Bash 继承环境或显式加载 profile，
  不增加 wrapper、BASH_ENV 或依赖主 runtime stage 的 OCI ENV。
- GCC 由 Nix、LLVM 由 Resource 提供，不改变 Framework/CUDA 兼容组合；Go/LLVM 精确
  目录用 minor/major 相对链接保持入口稳定。rustup/SDK 与运行期 CARGO_HOME 分离，
  `~/.cargo` 保留用户 CLI/cache。
- 依赖 `/workspace` 的 service 必须依赖 gocryptfs-workspace；credential 从 runtime secret
  读取，缺失直接失败。添加依赖不隐式启用可选服务，service 默认监听 loopback。
- package metadata 留在所属 image/manager，不重复安装；binman launcher/store/profile
  作为完整 payload，调用稳定入口，不硬编码 content-addressed store 内部路径。
- Conda ToS 用系统 metadata 供 root/x 共用；条款变化显式接受并同步 rootfs，不自动接受
  未来版本。
- 内置 rootless Podman 只服务 Workspace 用户，不连接 Host、不共享持久 storage 或迁移
  driver。保留 subordinate IDs/setuid helper/必要权限/unlimited pids；内部禁用 cgroups，
  构建用 chroot isolation，GPU CDI 按运行期注入设备/driver 生成。

## Main Flows

构建装配 rootfs/runtime/executable/graph，启动初始化用户与挂载后运行依赖服务。
[custom-job](rootfs/etc/s6/s6-rc.d/custom-job/run.sh) 以 `x` 从 Workspace key secret 解密
内部标识，替换 rootfs 模板并原子发布 profile 后安装；构建期不读 key。解密失败保留已有
profile，临时明文只在私有目录存放并退出清理，用户启动安装 job 不属于 image build。

macOS helper 从本仓库 GHCR/ORAS 获取，首次安装需先发布，不含 runtime/manager/Shell；
Linux image 从源码构建，不依赖 helper tag。构建/发布入口见
[publish-workspace-tools](../../../.github/workflows/publish-workspace-tools.yaml)。

## Pitfalls

- Linux LLVM archive 不含 sysroot；Clang 项目须显式配置 Nix GCC headers、启动对象与
  runtime/linker，不能用 `clang --version` 或单个 `--gcc-install-dir` 证明可用，也不加 wrapper
  或重复 compiler 隐藏限制。
- 系统认证依赖发行版 setuid su 与静态 sudo 可校验的 SHA-512 hash，软件替换/密码初始化
  不能丢失这两个条件。归档 Ollama 未预装 executable，恢复前按定义安装。
- ORAS setup Action 使用内嵌 release 列表；升级 CLI 同时核对 Action 的版本/平台支持。

## Validation

artifact 行为变化构建 Dockerfile 的最终 `workspace` target，验证无 Resource 也能启动。
AI 分发与正文一致性由 `platform/macos/tests/ai.bats` 检查；历史重写 helper 依赖 GNU
`date`，在 disposable repository 中验证，不改写本仓库历史。
Resource 可在仓库外临时配方裁剪无关工具，但保留受影响工具的真实 payload/binding/权限/
测试；接口变化同时检查主 image 的挂载、链接与调用。discovery 测试从真实 runtime 构造
链接，不借用 Homebrew/系统 Python 布局。完整矩阵由 CI 构建，交付说明裁剪与未验证范围；
共享 filesystem/s6 变化按根索引联动 Service/WSL。
