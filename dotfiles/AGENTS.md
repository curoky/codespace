# Dotfiles 约束

## 职责

`dotfiles/` 保存 Host 用户配置与跨环境复用的配置片段。目录按工具或产品组织，
不按 `shared`、`container`、`linux`、`macos` 等运行环境建立顶层分区。

Workspace image 专属 home 配置由
`platform/container/workspace/rootfs/home/x/` 持有，不移动或镜像到本目录。
Host 专属配置使用明确名称，例如 `git/macos.gitconfig` 和
`ssh/macos.config`、`zsh/macos.zshrc`。

## 安装边界

- `dotfiles/` 不提供通用 scene switch 或安装入口。
- Linux host 由 `platform/linux/install.sh` 显式选择并安装配置。
- macOS host 由 `platform/macos/install.sh` 显式选择并安装配置。
- Workspace image 仅可显式选择确需复用的 shell 片段、编辑器配置和用户命令，
  不得从本目录读取其专属 home 配置。
- 需要独立权限或会被运行时覆盖的配置使用 copy；其余配置使用 symlink。
- 用户命令安装到 `~/.local/bin`，源码位于 `dotfiles/bin/`。

## 修改规则

- 不提交凭据、编辑器缓存或本机状态。
- 不保留 `.bk`、archive、旧入口或注释掉的配置实现。
- zsh 公共职责拆到 `zsh/` 下具名片段；Workspace 入口固定为
  `platform/container/workspace/rootfs/home/x/.zshrc`。
- 新增或移动配置时，同步更新实际使用它的 Host installer 或 Workspace image。

## 验证

```bash
bash -n dotfiles/bin/*
zsh -n dotfiles/zsh/*.zsh dotfiles/zsh/macos.zshrc \
  platform/container/workspace/rootfs/home/x/.zshrc
shellcheck dotfiles/bin/*
shfmt -d dotfiles/bin/*
```
