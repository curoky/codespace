# vLLM Service Design

## Image Build

目标模型依赖尚未进入稳定发行版的能力，因此 image 从固定 commit index 安装
vLLM。commit、backend 与 wheel 版本只在 Dockerfile 中维护。

依赖来自 vLLM、PyTorch 与 PyPI 多个 index。解析必须允许跨 index 选择
满足约束的版本，避免专用 index 的旧辅助 package 抢占结果。
inference stack 安装在独立 venv，构建结果必须能直接运行。

vLLM 不依赖 runtime CUDA compilation。CUDA userspace library 由 wheel 提供，GPU
driver 由 Host 注入，因此 final image 不复制完整 CUDA Toolkit。

## Runtime

s6 只管理 serving longrun。`serve.sh` 固化目标 Host 的并行、MoE、cache 与上下文
profile；资源不足时通过其受控附加参数降低内存需求，不派生第二个 image。

模型 cache 由 managed Service data 提供。部署必须申请完整 GPU 与 IPC 能力，并
遵守父目录的网络和 SGLang 互斥约束。
