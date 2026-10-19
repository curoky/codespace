---
name: sync-macos-config
description: 管理本项目的 macOS 首次安装、home links 持续补齐和 LaunchAgent 可用性检查；当用户要求安装环境、同步配置链接或检查后台服务时调用。
---

# Sync macOS Config

从仓库根目录执行，先读 `platform/macos/AGENTS.md`。

## First Install

```bash
platform/macos/install.sh
```

首次安装完成后执行下面的 Link Sync 和 Service Check。

## Link Sync

配置内容由仓库中的 link source 直接生效。持续同步只需补齐 installer 新增或本机缺失的 links：

```bash
source platform/macos/install.sh
install_home_config
```

不要运行完整 installer，也不要逐文件复制 link 内容。

## Service Check

检查 `install.sh` 的 `main` 中默认启用的 LaunchAgent。当前为 `sh.atuin.daemon`：

```bash
domain="gui/$(id -u)"
launchctl print "$domain/sh.atuin.daemon"
atuin daemon status
test -S "$HOME/.local/share/atuin/atuin.sock"
tail -n 100 /tmp/atuin.daemon.log
```

要求 job 为 `running`、daemon status 正常、socket 存在且日志无持续错误。服务未加载或需要
重启时执行 `source platform/macos/install.sh && load_launch_agent sh.atuin.daemon`，然后重新
检查。不要启用 `main` 中被注释的可选服务。
