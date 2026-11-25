# java-tool

## Scope

为 image、Workspace 与 macOS 装配隔离 Java CLI；Coursier 拥有 Maven 解析、repository、
下载/cache，installer 只拥有布局、launcher 与 binding，不管理 catalog 或 JDK。
安装声明与实现见 [main.go](main.go)、[install.go](install.go)、[fetch.go](fetch.go)。

## Contracts

- launcher 相对 tools root 定位，payload 可搬迁，但固定 JDK binding 必须仍可用；
  `--inherit-java` 继承项目环境，不能同时显式选 JDK。Resource 只带 CLI 结果并用主 image
  JDK，校验用 JDK/临时 installer 环境不进入 payload。
- JVM 应用保留 resolver 顺序并复制完整 JAR/classpath，不依赖运行期 cache；发行包只取
  单个 artifact。显式 URL 必须提供 SHA-256，[archive.go](archive.go) 限制解包目录，
  拒绝路径逃逸、symbolic/hard link 与特殊 entry。
- tools root 解析真实路径，包括 macOS `/var` 别名；固定 JDK binding 保留声明路径。
  package/公开命令存在时失败，不支持 overwrite/upgrade/rollback/并发写入。

## Runtime I/O

- **Reads**：校验选定 JDK，使用 PATH 中 `cs`，读取其返回的本地 JAR/archive 与声明入口；
  Coursier 配置/cache 保持原生环境。
- **Writes**：默认 `~/.local/opt/java/tools`，`--root` 可改目标；写 environment、JAR 或解包
  payload、launcher，同 root staging 退出时尝试清理，Coursier cache 保留。不注册系统
  JDK 或修改 profile，执行已安装发行包的副作用不属于安装期保障。
- **Network**：从 Maven Central、额外 `--repository` 或显式 artifact URL 下载，不上传
  用户业务文件；支持格式与参数以实现为准。
- **Results & Failure**：输出安装包与命令；准备失败不覆盖已有安装，environment 发布后
  launcher 失败可留下不完整安装，不自动回滚。

## Validation

[install_test.go](install_test.go) 检查解包边界、冲突、binding 与搬迁。安装/binding 行为
变化覆盖主 image/Resource/macOS 的受影响路径，仅预装 artifact 变化验证所属 image；
非行为修改按根文档检查，不用真实安装替代定向测试。
