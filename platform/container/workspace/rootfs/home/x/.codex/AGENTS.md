# Workspace Agent Rules

## Container Environment

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

## Engineering Principles

- 简单优先且面向长期：选择能完整满足当前需求的最简实现，避免投机性的抽象、配置与间接层；同时做面向长期的架构决策，不接受注定日后被替换的权宜之计。
- 不要过度配置化以及过度提取常量。
- 不保留向后兼容性。移除过时的路径，而非添加兼容层、回退（fallback）或迁移逻辑。
- 分层演进系统。从能端到端跑通的最小版本起步，在已可运行的产品之上叠加每一项新能力。绝不用一个可运行的产品去换取未完成的复杂度。
- 保持组件模块化，关注点清晰分离。
- 依赖优先级：先善用项目中已有的依赖，再考虑引入成熟且维护良好的库降低复杂度或提升可靠性，最后才自行实现；不重复造轮子，也不在未查阅文档与类型定义前臆断某个库缺少某项能力。
- 现代技术优先。始终采用每种语言官方最新稳定且生态兼容的语法、功能、工具链与依赖；先核实版本状态，再锁定。
- 识别出一次性任务（如数据迁移、配置改造），用不入 Git 仓库的一次性代码完成。

## Collaboration

- 交互沟通默认用中文。写文档时中英混合，描述性主体用中文，标题、专用名词与业界通用概念保留英文，保证准确与可检索。
- 用给 AI 看的 AGENTS.md 替代给人看的 README.md，及时更新关键上下文；过大时按主题拆到同目录专题文档（如 `DESIGN.md`）并在 AGENTS.md 保留索引。
