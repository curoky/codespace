---
alwaysApply: true
---

# Container Environment

- 工具不可用时先加载 `/etc/profile.d/app.sh`，再检查实际路径与版本，不直接判定为未安装。
- 默认工具链与环境变量以该 profile 为准；项目声明的版本优先，在加载后设置项目覆盖，不另写默认版本清单。

| Toolchain | Layout & Usage |
| --- | --- |
| Python | uv 管理环境与项目依赖，`python`/`python3` 指向受管 runtime；用 `--python` 选择 `~/.local/opt/uv/python` 中的版本。全局 CLI 用 `uv tool`，不用全局 pip。 |
| Node.js | runtime 在 `~/.local/opt/node/nodejs*`，切换时将目标 `bin` 放到 PATH 首位。全局 CLI 用 `node-tool` 隔离安装到 `~/.local/opt/node/tools`，不用 npm/pnpm 全局安装。 |
| Java | runtime 在 `~/.local/opt/java/openjdk*`，切换时同步设置 `JAVA_HOME` 与 PATH。全局 CLI 用 `java-tool` 隔离安装到 `~/.local/opt/java/tools`。 |
| Rust | rustup 管理工具链，SDK 在 `~/.local/opt/rust`；`~/.cargo` 保留用户 CLI/cache，不与 SDK 根混用。 |
| Go | runtime 在 `~/.local/opt/go`，切换时将目标 `bin` 放到 PATH 首位；用户安装的命令在 `~/go/bin`。 |
| C/C++ | LLVM SDK 在 `~/.local/opt/llvm`，需挂载 Resource 后使用；GNU GCC 由 Nix 提供，不默认使用发行版旧 compiler。CUDA/Framework 的独立 compiler 约束不随默认工具链切换。 |

- 隔离 CLI 的固定 runtime binding 不随项目 PATH 切换，不为切换项目工具链而重装或改写全局 CLI。
- 确认缺少系统软件、全局 CLI 或 runtime 后，说明用途和安装方式，由用户手动安装，不擅自修改全局环境。
- 构建和运行开发容器使用 `/opt/podman/bin/podman`，它连接 Workspace 内的用户级 rootless Podman，不是 Host rootful Podman 的管理入口。
