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
| 个人 secret CLI/加密文件 | [Csecret](tools/csecret/AGENTS.md) |
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
[custom-job](rootfs/etc/s6/s6-rc.d/custom-job/run.sh) 以 `x` 从 csecret 读取初始化输入，
发布 LLMBox profile/auth 后执行安装；准备失败保留已有文件。GitHub/Atuin 登录同样
通过 csecret 获取凭据。构建期只装配密文，不读 key；安装任务只在服务启动时执行。

macOS helper 从本仓库 GHCR/ORAS 获取，首次安装需先发布，不含 runtime/manager/Shell；
Linux image 从源码构建，不依赖 helper tag。构建/发布入口见
[publish-workspace-tools](../../../.github/workflows/publish-workspace-tools.yaml)。

[Paseo](rootfs/home/x/.paseo/config.json) 由[默认 s6 service](rootfs/etc/s6/s6-rc.d/paseo/)
在 LLMBox 初始化与 Workspace 挂载就绪后启动，从 csecret 读取 `paseo_password` 提供 daemon/Web UI。
Dictation/Voice Mode 默认关闭，避免自动下载本地模型；以后在 Paseo 设置中按需开启。
手机直连 Host IP 的 publication 见[配置示例](../../../config.example.yaml)；仅限可信 LAN/VPN，
公网须额外配置 HTTPS 与防火墙，不通过 SSH tunnel。其他服务仍默认监听 loopback。

## Pitfalls

- Codex app-server 不接受 `-p`；Paseo 使用独立 `CODEX_HOME` 链接 LLMBox profile 与
  rules/skills，不继承 base config 或共享历史。`HOME` 不变，helper 复用原凭据。
- LLMBox 启动初始化以安装密文为准，会覆盖本地 auth；重新 login 后须显式回存并同步
  密文，否则下次启动恢复旧凭据。维护入口见 [use-secrets](rootfs/home/x/.codex/skills/use-secrets/SKILL.md)。
- Linux LLVM archive 不含 sysroot；Clang 项目须显式配置 Nix GCC headers、启动对象与
  runtime/linker，不能用 `clang --version` 或单个 `--gcc-install-dir` 证明可用，也不加 wrapper
  或重复 compiler 隐藏限制。
- 系统认证依赖发行版 setuid su 与静态 sudo 可校验的 SHA-512 hash，软件替换/密码初始化
  不能丢失这两个条件。root-password 以 `x` 从 csecret 读取 `codespace_root_password`，
  再由 root 调用 chpasswd；只接受非空单行密码，不挂载独立的 Podman password secret。
  WSL 显式跳过初始化。归档 Ollama 未预装 executable，恢复前按定义安装。
- ORAS setup Action 使用内嵌 release 列表；升级 CLI 同时核对 Action 的版本/平台支持。

## Validation

artifact 行为变化构建 Dockerfile 的最终 `workspace` target，验证无 Resource 也能启动。
Paseo 变化运行 [tests](../../../tests/test_workspace_paseo.py)，追加主 image 的原生模块、
daemon/Web UI、s6 readiness 与 Codex 验证；fixture 不证明真实 LLMBox 模型权限。
AI 分发与正文一致性由 `platform/macos/tests/ai.bats` 检查；历史重写 helper 依赖 GNU
`date`，在 disposable repository 中验证，不改写本仓库历史。
Resource 可在仓库外临时配方裁剪无关工具，但保留受影响工具的真实 payload/binding/权限/
测试；接口变化同时检查主 image 的挂载、链接与调用。discovery 测试从真实 runtime 构造
链接，不借用 Homebrew/系统 Python 布局。完整矩阵由 CI 构建，交付说明裁剪与未验证范围；
共享 filesystem/s6 变化按根索引联动 Service/WSL。
