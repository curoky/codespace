# Framework Images

本目录提供可直接运行或 `import` 的 framework 环境，不启动 s6，也不承担 Service
职责。

- 每个 framework/toolchain 组合使用独立 Dockerfile；文件名决定组合名和 image tag。
- 版本、CUDA architecture、构建依赖及默认组合以 Dockerfile 和 `build.sh` 为准。
- 编译发生在匹配的 builder image；final stage 只保留运行期资产。
- 需要 editable install 的 framework 必须在 final image 保留其源码。
- GPU driver 由 Host 的 NVIDIA Container Toolkit 注入，不打包进 image。

修改公共构建形态时检查三个 framework leaf；验证入口以各目录 `build.sh` 为准。
