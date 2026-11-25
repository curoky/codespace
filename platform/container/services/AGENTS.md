# Service Images

## Scope

提供 Host singleton daemon image；placement/mount/secret/device/publication/tunnel 属于
控制面，leaf 只拥有内部 runtime。构建先准备 shared s6，再装配 leaf 的 rootfs/静态 graph；
发布入口见 [workflow](../../../.github/workflows/publish-services.yaml)。

## Contracts

- [s6](s6/) 提供固定用户 `x`、init/日志/cron；上游无完整 aarch64-linux s6 stack，当前
  runtime/consumer 只发布 linux/amd64。Debian leaf 可继承 base，异构 leaf 只搬运
  `/usr/local`/skel/definition 并在自身 filesystem 编译 graph。
- leaf 不引入 Workspace SSH/deploy key/Agent/home profile/rootless Podman；专属 policy
  留在各自 rootfs，shared base 不增加 leaf policy。用户服务显式设置 HOME/cache。
- [support](support/) 是唯一拥有 Host rootful Podman socket maintenance 职责的 leaf，
  不将 mount/权限推广给其他 Service。

## Pitfalls

- [Chatbox](chatbox/) revision/pnpm/renderer/patch 作为构建单元；patch 用 `--fuzz=0`，
  避免上游变化被模糊套用，配置测试见 [test_chatbox.py](../../../tests/test_chatbox.py)。
- [SGLang](sglang/) source/PyTorch/kernel/deep-gemm/toolkit/JIT 必须同一 CUDA stack，
  删除 resolver 带入的错误 major 并保留 import/compile smoke check。
- [vLLM](vllm/) revision/distribution/Python/PyTorch CUDA index 同步，安装后检查实际 import version。

## Validation

image 行为变化构建受影响 leaf；共享 s6/Workspace install-s6/skel/日志/cron 变化构建全部
直接或间接 consumer。Chatbox 变化运行对应测试，具体构建输入以 Dockerfile 为准。
