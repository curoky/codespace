# Codespace

- 跨目录设计只写入根 `DESIGN.md`；不要新增下层 `DESIGN.md` 或 `README.md`。
- 独立实现根只有在存在局部 ownership、工具链或验证约束时才保留 `AGENTS.md`；
  中间目录不增加仅转述上层内容的文件。
- 注释只保留代码无法表达的约束或外部兼容性原因，不复述实现。
- 目录按领域组织，不增加无明确 ownership 的 `common`、`utils` 或 compatibility
  package。
- 不修改无关的用户、工作树或远端状态。
- Workspace image 的构建、运行、内置 rootless Podman 与验证约束见
  `platform/container/workspace/AGENTS.md`。
