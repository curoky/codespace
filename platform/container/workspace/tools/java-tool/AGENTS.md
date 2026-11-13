# java-tool

## Ownership

`java-tool` 是 resource image 构建和 workspace 运行期共用的单向 Java distribution
installer。Python CLI 只提供 `install`，Bash wrapper 提供自身环境的 `init`；不包含 package
catalog、下载器、JDK 管理、依赖解析或安装后的生命周期管理。

package name、version、已校验的本地 artifact、解包方式、launcher 映射和 JDK 选择全部由
调用方声明。resource image 预装集的版本、URL 与 SHA-256 只属于 `resource.Dockerfile`，
不得写入 Python 实现或本文件。

## Layout

```text
/opt/java/
├── java-tool/                   # installer 源码与 lockfile；加入 Workspace PATH
│   └── .venv/                   # installer 的独立 Python 环境
└── tools/
    ├── bin/                     # 已安装 CLI；加入 Workspace PATH
    └── envs/<package>/payload/   # 官方 distribution
```

launcher 相对自身位置查找同一 tools root 下的 env。`--java` 显式指定 JDK；launcher 设置
对应 `JAVA_HOME` 并将其 bin 放到子进程 PATH 首位。
Maven 等项目构建工具显式使用 `--inherit-java` 保留调用方环境。整个 tools family 可在
image stage 之间搬迁。

## CLI

```sh
java-tool init

java-tool install NAME@VERSION /tmp/release.tar.gz --extract \
  --executable command=bin/command --java /path/to/jdk

platform/container/workspace/tools/java-tool/java-tool \
  install NAME@VERSION /tmp/release.tar.gz \
  --extract \
  --executable command=bin/command \
  --executable-dir prefix-=support \
  --java /opt/java/openjdk27

platform/container/workspace/tools/java-tool/java-tool \
  install NAME@VERSION /tmp/tool.jar \
  --jar command=tool.jar \
  --java /opt/java/openjdk27
```

- wrapper 的 `init` 同步自身 `.venv`，内部固定 Python 版本，uv 的 Python 安装目录固定为
  `/opt/uv/python`，使用 `uv sync --locked --no-dev`。不接受额外参数；已有环境也会重新同步，
  成功后直接退出。
- `--executable COMMAND=PATH` 暴露 distribution 中的单个 executable。
- `--executable-dir PREFIX=DIR` 暴露目录内的 executable，命名为 `PREFIX<filename>`。
- `--jar COMMAND=PATH` 创建 `java -jar` launcher。
- `--inherit-java` 使用调用方的 `JAVA_HOME` 和 PATH，不固定 JDK。
- 每次安装必须显式选择 `--java` 或 `--inherit-java`，两者不能同时使用；没有默认 JDK。
- archive 必须是仅含一个顶层目录的 ZIP 或 TAR。
- 安装目标与 launcher 不允许已存在；resource image 应始终从空目录确定性构建，不实现
  overwrite、upgrade、rollback、并发写入或迁移。
- `java-tool` 是独立的 uv project，依赖由同目录 `pyproject.toml` 与 `uv.lock` 声明。workspace
  主 image 在 `/opt/java/java-tool` 同步 `.venv`；resource build 使用 `/tmp/java-tool`，不携带
  helper 的源码与环境进入 payload。两侧 build 调用 `init`，忽略调用方的 `VIRTUAL_ENV` 和
  `UV_PROJECT_ENVIRONMENT`。普通调用直接复用已有环境；自身 `.venv/bin/python` 不可执行时
  报错并提示运行 `init`。依赖变更后显式运行 `init`。

## Validation

```sh
uv lock --project platform/container/workspace/tools/java-tool --check
uv run ruff check platform/container/workspace/tools/java-tool
uv run ruff format --check platform/container/workspace/tools/java-tool
uv run mypy platform/container/workspace/tools/java-tool/java-tool.py
uv run pytest platform/container/workspace/tools/java-tool/test_java_tool.py --no-cov
```

修改预装 distribution 或 launcher 后，再运行：

```sh
platform/container/workspace/build.sh --resource
```
