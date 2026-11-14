# java-tool

为 resource image 构建和 Workspace 运行期提供单向 Java distribution 安装。调用方提供
已校验的本地 artifact、解包方式、launcher 映射与 JDK 选择；installer 不拥有 package
catalog、下载器或 JDK 管理。

## Contracts

- 每个 package 隔离安装，launcher 相对 tools root 定位，使安装结果可在 image stage 间搬迁。
- JDK 必须显式选择固定 runtime 或继承调用方环境；项目构建工具应继承项目的 Java 环境。
- tools root 可搬迁，固定绑定的 JDK 路径不能随意改变。resource 只携带 CLI 安装结果，
  launcher 使用主 image 的 JDK；构建时校验用的 JDK 和临时 installer 环境不进入 payload。
- 目标或公开命令已存在时失败，不扩展 overwrite、upgrade、rollback 或并发写入能力。
- installer 使用本目录独立的 uv project，与调用方 virtualenv 隔离；仅显式 `init` 同步
  环境，普通调用不安装依赖。修改依赖后必须重新 `init`，已有环境不会自动同步。

## Validation

通用检查遵循根文档。修改 installer 代码、wrapper 或依赖时，构建主 image 与 resource
image，分别覆盖运行期 helper 与预装产物。只修改预装 distribution 时构建 resource；涉及
主 image JDK 或路径契约时两者都构建。命令见上层 `AGENTS.md`。
