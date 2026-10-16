---
name: manage-software
description: 查找本机 command，并通过 Homebrew 安装缺失的 macOS 软件；当 command not found、需要确认工具路径或安装 CLI、runtime 或应用时调用。
---

# Manage Software

1. 运行 `command -v <command>`；软件通常位于 `/opt/bm/bin` 或 `/opt/homebrew/bin`。
2. 找不到时运行 `brew search <keyword>`，然后用 `brew install <formula>` 安装；GUI 应用使用
   `brew install --cask <cask>`。
3. 再运行 `command -v <command>` 和 `<command> --version` 验证。
