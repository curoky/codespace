# Codespace

- 跨目录架构只写入根 `DESIGN.md`；下层不新增 `DESIGN.md` 或 `README.md`。
- `AGENTS.md` 只记录当前实现根独有的 ownership、约束和验证，不复述上层内容。
- 注释只保留代码无法表达的约束或外部兼容性原因，不复述实现。
- 目录按领域组织，不增加无明确 ownership 的 `common`、`utils` 或 compatibility
  package。
- 不修改无关的用户、工作树或远端状态。
- 提交前运行 `task check`；行为变更运行 `task check:full`，artifact 变更再运行其目录的
  build 或 export 验证。
