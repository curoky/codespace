# Service 镜像约束

本目录保存 host 级单例 Service 镜像。`support`、`vllm`、`sglang` 均为直接子模块，
各自拥有完整的 Dockerfile、rootfs、构建脚本和 smoke 脚本。

## Identity 与构建

- 镜像固定为 `ghcr.io/curoky/codespace:service-<service>`。
- 容器名固定为 `codespace-service-<service>`。
- inventory label 固定为 `codespace.kind=service`、`codespace.service=<service>`、
  `codespace.image=<resolved-image>`；不得添加 Workspace label。
- 构建 context 固定为仓库根。Dockerfile 从
  `platform/container/workspace/rootfs/etc/s6/skel/` 与
  `platform/container/workspace/scripts/install-s6.sh` 复制 s6 bootstrap，
  Service rootfs 只拥有自身 s6-rc 定义。
- s6 默认 bundle 名为 `default`。Service 逻辑放入 `/opt/codespace/<service>/`。

## 运行边界

- Service 不属于 Project/Workspace 生命周期，不含 workspace mount、SSH 服务、deploy
  key、repository credential、provider token 或控制面。
- 对外服务只能经 host loopback 暴露。Linux 可使用 host network；macOS bridge
  publish 必须绑定 `127.0.0.1`。
- `support` 是唯一可 bind-mount host rootful Podman socket 的 Service，且只能按固定
  清单拉取镜像和清理 dangling image。
- vLLM/SGLang 不含 Podman socket，模型权重不进入镜像；cache 位于
  `~/codespace/services/<service>`。
- vLLM 与 SGLang 均占用全部 GPU 和端口 `8003`，同一 host 同时只能运行一个。

`build.sh` 负责本地构建；`smoke*.sh` 只验证镜像运行契约，并创建与控制面一致的
identity/labels，不形成第二套生产生命周期。修改公共约束时同步检查三个 leaf。
