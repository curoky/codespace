# java-tool

## Scope

为 image 构建、Workspace 与 macOS 装配隔离 Java CLI。Coursier 拥有 Maven 依赖解析、
repository、下载与 cache；installer 只拥有安装布局、launcher 与 Java binding，不管理
package catalog 或 JDK，也不提供 overwrite、upgrade、rollback 或并发写入能力。

## Contracts

- package 隔离安装，launcher 相对 tools root 定位；默认固定绑定用户级 JDK，覆盖只在
  确有需要时传递。项目构建工具用 `--inherit-java` 继承项目 Java 环境，不能同时显式选 JDK。
- tools root 可搬迁，固定 JDK binding 不可随意改变。Resource 只携带 CLI 结果，使用主
  image JDK；构建时校验用的 JDK 与临时 installer 环境不进入 payload。
- JVM 应用保留 Coursier 的依赖顺序，复制完整 JAR 集合并生成相对 classpath，不依赖运行期
  cache；发行包只获取单个 artifact，再校验解包。显式 URL 必须提供 SHA-256。
- [archive.go](archive.go) 使用 `mholt/archives`，只接受 ZIP/TAR；拒绝路径逃逸、symbolic
  link、hard link 与特殊 entry，通过 `os.Root` 将写入限制在临时解包目录。
- launcher 解析 tools root 的真实路径，包括 macOS `/var` 别名；JAR 使用解析后的路径，
  固定 JDK binding 保留调用方声明路径。package 或公开命令已存在时失败，不覆盖。

## Main Flows

[install.go](install.go) 校验安装声明，经 [fetch.go](fetch.go) 获取 artifact；JVM 应用
复制 JAR，发行包校验并解包。检查 payload、launcher 目标与命令冲突后发布 environment，
再写 launcher；参数与布局以 [main.go](main.go) 和实现为准，不另维护 package 清单。

## Runtime I/O

- **Reads**：读取选定 JDK、PATH 中的 `cs`、Coursier 返回的本地 JAR/archive，以及声明
  的入口。Coursier 的配置和 cache 遵循其原生环境。
- **Writes**：默认写入 `~/.local/opt/java/tools`，`--root` 可改变目标；包括独立 environment、
  JAR 或解包 payload、`bin` launcher。同 root 内 staging 退出时尝试清理，Coursier cache 保留。
- **Network**：Coursier 从 Maven Central、额外 `--repository` 或显式 artifact URL 下载；
  目标与查询由安装参数确定，不上传用户业务文件。
- **Results & Failure**：成功输出安装包与公开命令。准备失败不覆盖已有安装；environment
  发布后 launcher 写入失败可能留下不完整安装，不自动回滚。installer 不注册系统 JDK、
  不修改 Shell profile，launcher 执行发行包后产生的副作用不属于安装期保障。

## Validation

[install_test.go](install_test.go) 验证 artifact、解包边界、冲突、binding 与路径搬迁。
installer/binding 变化验证主 image、Resource 和 macOS；只改预装 artifact 时验证所属
image，不运行真实安装来替代定向测试。
