# Framework Images

Framework image 只提供可直接运行或 `import` 的计算环境，不承担 Service
生命周期。

- 每个 framework/toolchain 组合使用独立 Dockerfile；文件名是 combo 与 image tag
  的 canonical identity。
- 编译发生在匹配的 builder stage；final stage 只保留运行期资产。
- 需要 editable install 的 framework 必须在 final image 保留其源码。
- GPU driver 由 Host 的 NVIDIA Container Toolkit 注入，不打包进 image。
- 未知 combo 必须 fail-fast；修改公共构建形态时验证所有 framework leaf。
