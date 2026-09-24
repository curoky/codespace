# java-tool

## Ownership

`java-tool` 是 resource image 构建期使用的通用 Java distribution installer。它只提供
`install`，不包含 package catalog、下载器、JDK 管理、依赖解析或安装后的生命周期管理。

package name、version、已校验的本地 artifact、解包方式和 launcher 映射全部由调用方声明。
具体工具的版本、URL 与 SHA-256 只属于 `resource.Dockerfile`，不得写入 Python 实现。

## Layout

```text
/opt/java/tools/
├── bin/                         # 加入 Workspace PATH
└── envs/<package>/payload/      # 官方 distribution
```

launcher 是普通 POSIX shell 文件，显式设置安装时由 `--java` 指定的 `JAVA_HOME`，并把该
JDK 的 `bin` 放在子进程 PATH 首位。它不受 Workspace 当前 `JAVA_HOME`、mise、SDKMAN!
或 project toolchain 配置影响。

## CLI

```sh
uv run --locked --script java-tool.py install NAME@VERSION /tmp/release.tar.gz \
  --extract \
  --executable command=bin/command \
  --executable-dir prefix-=support \
  --java /opt/java/openjdk27

uv run --locked --script java-tool.py install NAME@VERSION /tmp/tool.jar \
  --jar command=tool.jar \
  --java /opt/java/openjdk27
```

- `--executable COMMAND=PATH` 暴露 distribution 中的单个 executable。
- `--executable-dir PREFIX=DIR` 暴露目录内的 executable，命名为 `PREFIX<filename>`。
- `--jar COMMAND=PATH` 创建 `java -jar` launcher。
- archive 必须是仅含一个顶层目录的 ZIP 或 TAR。
- 安装目标与 launcher 不允许已存在；resource image 应始终从空目录确定性构建。

## Validation

```sh
uv lock --script platform/container/workspace/tools/java-tool/java-tool.py --check
uv run ruff check platform/container/workspace/tools/java-tool
uv run ruff format --check platform/container/workspace/tools/java-tool
uv run mypy platform/container/workspace/tools/java-tool/java-tool.py
uv run pytest platform/container/workspace/tools/java-tool/test_java_tool.py --no-cov
```

修改预装 distribution 或 launcher 后，再运行：

```sh
platform/container/workspace/build.sh --resource
```
