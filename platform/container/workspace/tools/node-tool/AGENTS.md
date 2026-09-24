# node-tool

## Purpose

`node-tool` 用接近 `uv tool install` 的方式安装由 Node.js 编写的 CLI：每个 npm package
拥有独立的 `node_modules`，公开命令集中放在 `/opt/node/tools/bin`，并永久绑定调用者指定
的外部 Node.js runtime。

它解决以下确定场景：

- Node.js 已由 resource image 安装到 `/opt/node/<version>`，本工具不管理 Node.js。
- pnpm 已作为原生 executable 安装，本工具只把它作为 dependency resolver 和 installer。
- npm CLI 在 image build 中一次性安装；升级和删除通过修改 Dockerfile 后重建 image 完成。
- 调用 CLI 时，外层 `PATH` 不需要包含 Node.js，也不受 `mise.toml`、`.nvmrc` 等项目配置
  影响。

因此 CLI 只保留 `install`，不提供 `list`、`uninstall`、`upgrade`、并发修改或迁移能力。

## Layout

```text
/opt/node/tools/
├── bin/
│   ├── pnpm                    # Dockerfile 直接安装的 Rust executable
│   ├── prettier                # node-tool 生成的 launcher
│   └── markdownlint-cli2       # node-tool 生成的 launcher
├── envs/
│   ├── prettier/               # 独立 pnpm project
│   └── markdownlint-cli2/      # 独立 pnpm project
└── store/                      # pnpm shared content-addressable store
```

`install` 创建临时 pnpm project，只安装一个直接依赖，从安装结果的
`package.json#bin` 发现 executable，然后将环境移入 `envs/<package>` 并生成 launcher。
pnpm 负责 package spec、registry、依赖解析和 lockfile；Python 不重复实现这些能力。

launcher 将指定 Node.js 的 `bin` 放到子进程 `PATH` 首位，再执行环境中的
`node_modules/.bin/<command>`。该 PATH 只影响工具进程及其子进程，不会向调用者 shell
暴露 `node`。

## CLI

源码是带 PEP 723 metadata 的单文件应用，唯一 Python 依赖是 Typer，由 uv lock：

```sh
uv run --script platform/container/workspace/tools/node-tool/node-tool.py install \
  prettier@3.9.9 \
  --node /opt/node/nodejs24 \
  --pnpm /opt/node/tools/bin/pnpm
```

默认值适配 Workspace resource image：

- `--node /opt/node/nodejs24`
- `--pnpm /opt/node/tools/bin/pnpm`
- `--root /opt/node/tools`

安装目标环境或任一公开命令已经存在时直接失败。image build 必须从干净 stage 开始，不在
这里实现覆盖、回滚或 ownership metadata。

## Workspace Integration

`resource.Dockerfile` 直接下载并校验 `@pnpm/exe.linux-x64@12.6.0`，将其原生 executable
安装为 `/opt/node/tools/bin/pnpm`。它不依赖外部 Node.js，且不属于 node-tool 管理的环境。

随后 node-tool 安装：

- `markdownlint-cli2@0.23.3`
- `prettier@3.9.9`

两者均绑定 `/opt/node/nodejs24`。构建阶段使用不含 Node.js 的最小 `PATH` 分别启动 pnpm
和两个 launcher，验证 runtime 边界。主 Workspace image 不再从 Nix 安装这些同名命令。

## Validation

```sh
uv lock --script platform/container/workspace/tools/node-tool/node-tool.py --check
uv run ruff check platform/container/workspace/tools/node-tool
uv run ruff format --check platform/container/workspace/tools/node-tool
uv run mypy platform/container/workspace/tools/node-tool/node-tool.py
uv run pytest platform/container/workspace/tools/node-tool/test_node_tool.py --no-cov
podman build . --isolation chroot --network=host \
  --file platform/container/workspace/resource.Dockerfile \
  --target stage_node \
  --tag codespace-node-tool-test
```
