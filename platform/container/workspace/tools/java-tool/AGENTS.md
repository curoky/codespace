# java-tool

## Scope

为 image 构建、Workspace 与 macOS 装配隔离的 Java CLI。Coursier 负责 Maven 依赖解析、
repository、下载与 cache；installer 负责安装布局、launcher 与 Java binding，
不拥有 package catalog 或 JDK 管理。

## Contracts

- 每个 package 隔离安装，launcher 相对 tools root 定位，使安装结果可在 image stage 间搬迁。
- JVM 应用保留解析器给出的依赖顺序，复制完整 JAR 集合并生成相对 classpath；不依赖运行期
  cache。发行包只获取单个 artifact，再校验并解包；显式 URL artifact 必须提供 SHA-256。
- 默认绑定用户级 JDK；runtime 覆盖只在确有需要时显式传递。项目构建工具通过
  `--inherit-java` 继承项目的 Java 环境，不能与显式 JDK 选择同时使用。
- tools root 可搬迁，固定绑定的 JDK 路径不能随意改变。resource 只携带 CLI 安装结果，
  launcher 使用主 image 的 JDK；构建时校验用的 JDK 和临时 installer 环境不进入 payload。
- launcher 解析 tools root 的真实路径，包括 macOS 的 `/var` 别名；JAR 参数使用解析后的
  路径，但固定 JDK binding 保留调用方声明的路径。
- 目标或公开命令已存在时失败，不扩展 overwrite、upgrade、rollback 或并发写入能力。
- archive 识别与读取使用 `mholt/archives`，只接受 ZIP 与 TAR。拒绝路径逃逸、symbolic
  link、hard link 与特殊 entry；写入通过 `os.Root` 限制在临时解包目录。

## Validation

通用检查遵循根文档。installer 或 binding 变化验证主 image、Resource 与 macOS；
只修改预装 artifact 时验证所属 image。命令见上层 `AGENTS.md`。
