# Container Environment

- 工具环境由 `/etc/profile.d/app.sh` 提供；Zsh 与登录 Bash 自动加载，其他入口按需加载。
- Python 环境与项目依赖统一使用 uv，按需用 `--python` 选择预装版本。
- 缺少系统软件、全局 CLI 或 runtime 时，说明用途和安装方式，由用户手动安装。
- `/opt/resource` 是只读 payload；项目工具链调整在加载容器环境后进行。
