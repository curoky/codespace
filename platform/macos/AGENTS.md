# macOS Platform 约束

## 职责

`platform/macos/` 拥有 macOS host 的声明式安装入口、Homebrew 与 binman manifest、
LaunchAgent，以及仅在 macOS 上运行的辅助脚本。

## 安装契约

- 唯一入口是 `install.sh`，必须从自身路径定位仓库，不依赖固定 checkout 目录。
- installer 显式列出每个 dotfile 的 source 与 target，不调用通用 scene switch。
- 重复执行必须得到相同结果；受管 target 可以被同一 source 的 symlink 或配置副本替换。
- Host zsh 入口固定为 `dotfiles/zsh/macos.zshrc`，共享片段安装到
  `~/.config/zsh/`；Git global ignore 安装到 `~/.config/git/ignore`。
- 默认只安装并加载 Atuin daemon。Atuin server 必须通过 `--with-atuin-server` 显式启用。
- `start-podman` 与 `start-colima` 是独立命令，installer 不自动同时启动两个 runtime。
- LaunchAgent 不保存真实 token、密码或远程数据库连接串。

## 验证

```bash
bash -n platform/macos/install.sh platform/macos/scripts/*.sh
plutil -lint platform/macos/launch-agents/*.plist
shellcheck platform/macos/install.sh platform/macos/scripts/*.sh
shfmt -d platform/macos/install.sh platform/macos/scripts/*.sh
```
