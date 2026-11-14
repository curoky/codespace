# node-tool

## Ownership

`node-tool` 是 workspace image 构建和运行期共用的单向 npm CLI installer。每个
package 拥有隔离的 pnpm project，公开命令集中写入 `/opt/node/tools/bin`，launcher 永久绑定
调用者指定的外部 Node.js runtime，并相对自身位置查找同一 tools root 下的 env。

它不管理 Node.js、pnpm、package catalog 或运行期升级。package spec、版本、pnpm artifact
和选定 Node.js path 只属于调用方；预装集由 workspace `Dockerfile` 决定，
Python 实现不复制这些数据。

## Layout

```text
/opt/node/
├── node-tool/                   # installer 源码与 lockfile；加入 Workspace PATH
│   └── .venv/                   # installer 的独立 Python 环境
└── tools/
    ├── bin/                     # 已安装 CLI；加入 Workspace PATH
    └── envs/<package>/           # 隔离的 pnpm project
```

## Install Contract

```bash
node-tool init

node-tool install package@version --node /path/to/node \
  [--registry https://registry.example.com] \
  [--allow-build package-with-lifecycle-script]

platform/container/workspace/tools/node-tool/node-tool install \
  package@version \
  --node /opt/node/nodejs24 \
  --pnpm /usr/local/bin/pnpm
```

- wrapper 的 `init` 同步自身 `.venv`，内部固定 Python 版本，uv 的 Python 安装目录固定为
  `/opt/uv/python`，使用 `uv sync --locked --no-dev`。不接受额外参数；已有环境也会重新同步，
  成功后直接退出。
- `install` 创建只含一个 direct dependency 的临时 pnpm project，由 pnpm 负责 registry、
  resolution、lockfile 与 shared store。
- `--node` 必须显式指定 Node.js runtime 根目录；没有默认 runtime，也不从 PATH 推断。
- `--registry` 可选，只为本次 `pnpm add` 指定 npm registry；省略时沿用 pnpm 的现有配置。
- `--allow-build` 可重复，只允许列出的 package 运行 lifecycle scripts；默认不授权，pnpm
  仍负责检测并拒绝未授权的 build scripts。白名单属于调用方的 package metadata。
- executable 只从安装结果的 `package.json#bin` 发现；不要维护手写的 package-to-command
  registry。
- 成功后环境整体移入 `envs/<package>`，每个 launcher 把指定 Node.js `bin` 放到子进程 PATH
  首位，再执行该环境的 `node_modules/.bin/<command>`。
- 调用者 PATH 不需要 Node.js，也不受 project 的 mise/nvm 配置影响；绑定只作用于 CLI 及其
  子进程。
- 目标环境或任一公开命令已存在时直接失败。image build 从空 stage 开始，不实现 overwrite、
  uninstall、upgrade、rollback、并发写入或迁移。
- pnpm 是 bm 安装到 `/usr/local` 的 native executable，不属于 node-tool 管理环境。
- `node-tool` 是独立的 uv project，依赖由同目录 `pyproject.toml` 与 `uv.lock` 声明。workspace
  主 image 在 `/opt/node/node-tool` 同步 `.venv`；CLI 构建 stage 使用 `/tmp/node-tool`，不携带
  临时 helper 的源码与环境进入最终 image。各 build 调用 `init`，忽略调用方的 `VIRTUAL_ENV` 和
  `UV_PROJECT_ENVIRONMENT`。普通调用直接复用已有环境；自身 `.venv/bin/python` 不可执行时
  报错并提示运行 `init`。依赖变更后显式运行 `init`。

## Validation

```bash
uv lock --project platform/container/workspace/tools/node-tool --check
uv run ruff check platform/container/workspace/tools/node-tool
uv run ruff format --check platform/container/workspace/tools/node-tool
uv run mypy platform/container/workspace/tools/node-tool/node-tool.py
uv run pytest platform/container/workspace/tools/node-tool/test_node_tool.py --no-cov
podman build . --network=host \
  --file platform/container/workspace/Dockerfile \
  --target stage_node \
  --tag codespace-node-tool-test
```

修改 package set、runtime binding 或最终 profile 时再构建完整 workspace image。
