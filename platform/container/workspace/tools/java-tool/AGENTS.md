# java-tool

## Ownership

`java-tool` 是 resource image 构建和 workspace 运行期共用的单向 Java distribution
installer。它只提供 `install`，不包含 package catalog、下载器、JDK 管理、依赖解析或安装后
的生命周期管理。

package name、version、已校验的本地 artifact、解包方式、launcher 映射和选定 JDK 全部由
调用方声明。resource image 预装集的版本、URL 与 SHA-256 只属于 `resource.Dockerfile`，
不得写入 Python 实现或本文件。

## Layout

```text
/opt/java/tools/
├── bin/                         # 加入 Workspace PATH
└── envs/<package>/payload/      # 官方 distribution
```

launcher 是普通 POSIX shell 文件，相对自身位置查找同一 tools root 下的 env，显式设置安装时
由 `--java` 指定的 `JAVA_HOME`，并把该 JDK 的 `bin` 放在子进程 PATH 首位。因此整个 Java
family 可以在 image stage 之间搬迁；launcher 不受 Workspace 当前 `JAVA_HOME`、mise、
SDKMAN! 或 project toolchain 配置影响。

## CLI

```sh
java-tool install NAME@VERSION /tmp/release.tar.gz --extract \
  --executable command=bin/command

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
- 安装目标与 launcher 不允许已存在；resource image 应始终从空目录确定性构建，不实现
  overwrite、upgrade、rollback、并发写入或迁移。
- workspace 主 image 暴露 `java-tool` 命令，包装为 `uv run --locked --script` 调用同目录脚本；
  resource build 继续直接执行源码。

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
