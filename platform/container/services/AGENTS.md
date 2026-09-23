# Service Images

- leaf image 只拥有自身 runtime 资产；共享 s6 base 变化必须验证所有 Service leaf。
- `chatbox/` 的 upstream version、pnpm version 与 `defaults.patch` 是一个构建单元；
  patch 必须保持 `--fuzz=0`。
- `vllm/` 的 commit、Python version 与 PyTorch CUDA index 是一个 wheel compatibility
  unit。
