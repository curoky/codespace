# java-tool

为 resource image 构建、Workspace 运行期与 macOS maintenance 提供单向 Java distribution
安装。调用方提供已校验的本地 artifact、解包方式与 launcher 映射；installer
不拥有 package catalog、下载器或 JDK 管理。

## Contracts

- 每个 package 隔离安装，launcher 相对 tools root 定位，使安装结果可在 image stage 间搬迁。
- 默认 tools root 从当前用户的 Home 派生；构建 stage 显式设置固定用户的 HOME。
- 默认绑定用户级 JDK；runtime 覆盖只在确有需要时显式传递。项目构建工具通过
  `--inherit-java` 继承项目的 Java 环境，不能与显式 JDK 选择同时使用。
- tools root 可搬迁，固定绑定的 JDK 路径不能随意改变。resource 只携带 CLI 安装结果，
  launcher 使用主 image 的 JDK；构建时校验用的 JDK 和临时 installer 环境不进入 payload。
- 目标或公开命令已存在时失败，不扩展 overwrite、upgrade、rollback 或并发写入能力。
- installer 是独立 Go executable，与 Agent、node-tool 共用上层 Go module；无运行期
  Python、uv 或编译器依赖，不提供 `init`。Bash launcher 通过 `text/template` 渲染，模板
  由 `go:embed` 编译进 executable；路径使用 Shell quoting，不依赖外部模板文件。
- archive 识别与读取使用 `mholt/archives`，只接受 ZIP 与 TAR。拒绝路径逃逸、symbolic
  link、hard link 与特殊 entry；写入通过 `os.Root` 限制在临时解包目录。

## Validation

通用检查遵循根文档。修改 installer 代码、模板或依赖时，构建主 image 与 resource
image，分别覆盖运行期 helper 与预装产物，并验证 macOS maintenance。只修改预装 distribution
时构建 resource；涉及主 image JDK 或路径契约时两者都构建。命令见上层 `AGENTS.md`。
