# node-tool

## Ownership

`node-tool` 是 resource image 构建期使用的单向 npm CLI installer。每个 package 拥有隔离的
pnpm project，公开命令集中写入 `/opt/node/tools/bin`，launcher 永久绑定调用者指定的外部
Node.js runtime。

它不管理 Node.js、pnpm、package catalog 或运行期升级。package spec、版本、pnpm artifact
和选定 Node.js path 只属于 `resource.Dockerfile`；Python 实现不复制这些数据。

## Install Contract

```bash
uv run --script \
  platform/container/workspace/tools/node-tool/node-tool.py install \
  package@version \
  --node /opt/node/nodejs24 \
  --pnpm /opt/node/tools/bin/pnpm
```

- `install` 创建只含一个 direct dependency 的临时 pnpm project，由 pnpm 负责 registry、
  resolution、lockfile 与 shared store。
- executable 只从安装结果的 `package.json#bin` 发现；不要维护手写的 package-to-command
  registry。
- 成功后环境整体移入 `envs/<package>`，每个 launcher 把指定 Node.js `bin` 放到子进程 PATH
  首位，再执行该环境的 `node_modules/.bin/<command>`。
- 调用者 PATH 不需要 Node.js，也不受 project 的 mise/nvm 配置影响；绑定只作用于 CLI 及其
  子进程。
- 目标环境或任一公开命令已存在时直接失败。image build 从空 stage 开始，不实现 overwrite、
  uninstall、upgrade、rollback、并发写入或迁移。
- pnpm 可以是 Dockerfile 独立安装的 native executable；它不属于 node-tool 管理环境。

## Validation

```bash
uv lock --script platform/container/workspace/tools/node-tool/node-tool.py --check
uv run ruff check platform/container/workspace/tools/node-tool
uv run ruff format --check platform/container/workspace/tools/node-tool
uv run mypy platform/container/workspace/tools/node-tool/node-tool.py
uv run pytest platform/container/workspace/tools/node-tool/test_node_tool.py --no-cov
docker build . --network=host \
  --file platform/container/workspace/resource.Dockerfile \
  --target stage_node \
  --tag codespace-node-tool-test
```

修改 package set、runtime binding 或最终 profile 时再构建完整 resource image。
