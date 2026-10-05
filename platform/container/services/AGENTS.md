# Service Images

此目录拥有由控制面按 Host singleton 管理的 daemon image。部署 placement、mount、secret、
device、publication 和 tunnel 属于控制面配置；leaf Dockerfile 只定义 image 内 runtime。

## Shared Runtime

- `s6/` 是 Debian Service leaf 的 shared runtime，提供固定用户 `x`、s6 init、日志与 cron
  基础。修改后必须重新构建所有直接或间接 consumer。
- Debian leaf 可以继承 `service-s6`。异构 base 只从 s6 stage 复制可搬运的 `/usr/local`、
  skel 和 service definition，并在自己的 filesystem 上运行 `install-s6.sh` 编译 graph。
- leaf 只复制自身 `rootfs/` 和 service definition，不引入 Workspace SSH、deploy key、Agent、
  home profile 或 rootless Podman。
- `support/` 是唯一明确拥有 Host rootful Podman socket maintenance 职责的 leaf；不要把该
  mount 或权限推广到其他 Service。

## Leaf Contracts

- `chatbox/`：upstream version、pnpm version、renderer build 与 `defaults.patch` 是一个构建
  单元；patch 必须使用 `--fuzz=0`，避免上游变化被模糊套用。配置测试在
  `tests/test_chatbox.py`。
- `sglang/`：source revision、PyTorch、kernel、deep-gemm、CUDA toolkit 和 JIT compiler
  必须保持同一 CUDA stack；显式删除 resolver 带入的错误 CUDA major，并保留 import/compile
  smoke check。
- `vllm/`：commit、distribution version、Python 与 PyTorch CUDA index 是一个 wheel
  compatibility unit；安装后校验实际 import version。
- `secret/` 与 `support/`：保持 payload 最小，cron/service 行为写入各自 rootfs，不在 shared
  base 增加 leaf-specific policy。

## Validation

使用 repository root 作为 context 构建每个受影响 leaf，例如：

```bash
docker build . --file platform/container/services/<service>/Dockerfile \
  --tag codespace-service-<service>-test
```

共享 `s6/`、Workspace 的 `install-s6.sh`、skel、日志或 cron source 变化时，构建全部 Service
leaf。Chatbox 变化再运行 `uv run pytest tests/test_chatbox.py`；脚本变化运行 `task check:full`。
