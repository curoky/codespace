---
description: 在 codespace Workspace 中执行 shell 命令、查找 Python/Java/Node.js/Go/Rust/C++ 工具链或排查 command not found 时使用
alwaysApply: true
---

<!-- markdownlint-disable MD013 -->

# Workspace 工具链地图（给 AI Agent）

优先用登录 shell 跑命令，避免非登录 shell 缺 PATH：

```bash
zsh -lic '<cmd>'
```

若仍找不到工具，按下表用绝对路径。

## 工具链

| 场景 | 路径 / 用法 |
| --- | --- |
| Python | 优先 `/opt/bm/bin/uv run <cmd>`；`ruff` 在 `/opt/bm/bin/ruff` |
| CPython | `/opt/uv/python/cpython-3.<N>-linux-x86_64-gnu/bin/python3`，`N=9..14` |
| Conda | `/opt/conda/condabin/conda`，仅 conda 生态需要时用 |
| Java | JDK 25: `JAVA_HOME=/nix/var/nix/profiles/jdk25/lib/openjdk`；JDK 8: `/nix/var/nix/profiles/jdk8/lib/openjdk` |
| Maven | `/home/x/.nix-profile/bin/mvn` |
| Node.js | `/home/x/.nix-profile/bin/node`、`npm`、`npx`、`corepack` |
| pnpm | `/opt/bm/bin/pnpm`、`/opt/bm/bin/pnpx` |
| Go | `/home/x/.nix-profile/bin/go`、`gofmt` |
| Go tools | `/opt/bm/store/<name>/bin/<name>`，如 `gopls`、`golangci-lint`、`dlv` |
| Rust | `/opt/rust/cargo/bin/cargo`、`rustc`、`clippy`、`rustfmt`、`rust-analyzer` |
| Rust env | 非登录 shell 需 `CARGO_HOME=/opt/rust/cargo RUSTUP_HOME=/opt/rust/rustup` |
| C/C++ | `/home/x/.nix-profile/bin/gcc`、`g++`；`clang-format` 在 `/opt/bm/store/clang-tools-*/bin/clang-format` |
| 构建工具 | `/opt/bm/bin/cmake`、`ninja`、`bazel`、`protoc`、`task` |
| Shell | `/opt/bm/bin/shfmt`、`shellcheck`、`bats` |
| 常用 CLI | `/opt/bm/bin` 下有 `git`、`gh`、`rg`、`fd`、`jq`、`curl`、`ssh`、`rsync`、`zip` 等 |

## 安装工具

- Python CLI：`uv tool install <tool>`。
- Node CLI：优先项目内 `pnpm add -D <tool>`。
- 系统包：`nix-env -iA nixpkgs.<pkg>`；`apt` 需要 `sudo`。
