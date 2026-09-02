# Dotfiles

`dotfiles/` 保存 Host 配置与跨环境复用片段，按工具组织，不按运行环境建立顶层分区。

- Workspace-owned home 配置留在 `platform/container/workspace/rootfs/home/x/`；
  Host 需要时直接链接，不在这里复制。
- 安装逻辑属于 `platform/<host>/`；本目录不提供 scene switch。
- installer 必须显式选择 source 与 target。需要独立权限或会被覆盖的文件使用 copy，
  其余使用 symlink。
- Host 差异通过工具目录内的明确文件名表达。
- 不提交 credential、生成状态、backup、archive 或旧入口。
- 新增或移动配置时同步更新实际消费者。

语法和行为验证统一从根目录 `task check` 进入；zsh 配置额外使用 `zsh -n`。
