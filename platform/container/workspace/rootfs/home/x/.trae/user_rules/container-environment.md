---
alwaysApply: true
---

# Container Environment

- 工具环境缺失时加载 `/etc/profile.d/app.sh`；项目工具链覆盖在加载后设置。
- Python 环境与项目依赖使用 uv，按需用 `--python` 选择预装版本。
- Node.js 优先使用 26；按项目需求从 `/opt/node/nodejs*` 选择版本，将其 `bin` 放到 PATH 首位。
- 切换 Java 时，将 `JAVA_HOME` 设为选定的 `/opt/java/openjdk*`，并将其 `bin` 放到 PATH 首位。
- 缺少系统软件、全局 CLI 或 runtime 时，说明用途和安装方式，由用户手动安装。
- 构建和运行开发容器使用 `/opt/podman/bin/podman`。
